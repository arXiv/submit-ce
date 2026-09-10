"""Turn a validated wrapper into a submit-ce submission.

Legacy handed a flat field hash to ``arXiv::Submit::Submission->new`` and let it
write the legacy tables directly (``AtomPP.pm:1182-1230``). Here the same
information becomes domain events, so a SWORD deposit produces exactly the event
stream an interactive submission does -- which is the whole point of doing this
inside submit-ce rather than beside it.

Legacy forked at this point and returned 202 from the parent while a child created
and processed the submission (``AtomPP.pm:1257-1268``). This runs the submission
creation *synchronously* and returns 202 afterwards: the 202 contract promises
asynchronous **ingestion**, not a deferred create, and doing it inline means the
tracking row exists the moment the client is told where to look.

Compilation and `FinalizeSubmission` are **not** done here. `FinalizeSubmission`
requires ``source_format``, which only preflight can determine, so finalizing is
left to the async compile path.
"""

import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import IO, List, Optional, Tuple

import arxiv.db.models as models
from arxiv.license import LICENSES
from sqlalchemy.orm import Session as SqlalchemySession

from submit_ce.api import SubmitApi
from submit_ce.domain import Author, Event
from submit_ce.domain.agent import Client, User
from submit_ce.domain.event import (
    AddSecondaryClassification,
    ConfirmPolicy,
    CreateSubmission,
    SetAbstract,
    SetACMClassification,
    SetComments,
    SetDOI,
    SetJournalReference,
    SetLicense,
    SetMSCClassification,
    SetPrimaryClassification,
    SetProxyInformation,
    SetReportNumber,
    SetTitle,
)
from submit_ce.domain.event.file import UploadArchive, UploadFiles
from submit_ce.sword.atom.parse import WrapperMetadata
from submit_ce.sword.deposits import DepositStore

logger = logging.getLogger(__name__)

SWORD_AGREEMENT_ID = 1
"""Policy agreement recorded for a SWORD deposit.

SWORD depositors accept arXiv's terms out of band: registration plus explicit
authorisation by arXiv admins (``submit_sword.md:98-101``) and a default license
registered in advance at ``/sword-license`` (``submit_sword.md:122-127``), which is
a hard precondition of every request. There is no interactive agreement step in the
protocol, so acceptance is asserted here on the strength of those.
"""

TRACKING_IN_PROGRESS = "submit/{submission_id}"
"""``arXiv_tracking.paper_id`` while a deposit is still in the workflow.

The column is overloaded as a state field: this form until announcement, then the
real paper id, or a string containing ``failed`` (``Controller/Sword.pm:29-31``).
"""


@dataclass
class StagedFile:
    """A `SubmitFile`-shaped view of staged deposit bytes.

    The upload events want something with ``filename``, ``content_type`` and
    ``stream``; staged deposits are bytes in a bucket.
    """

    filename: str
    content_type: str
    stream: IO[bytes]


def license_name_for(uri: str) -> str:
    """Display name for a license URI, for `SetLicense`."""
    entry = LICENSES.get(uri) or {}
    return entry.get("label") or entry.get("name") or uri


def metadata_events(metadata: WrapperMetadata,
                    *,
                    creator: User,
                    client: Client,
                    depositor: str,
                    license_uri: str) -> List[Event]:
    """The event sequence for a wrapper's metadata, excluding file uploads.

    Order mirrors legacy's field hash (``AtomPP.pm:1182-1197``); only the optional
    elements that were actually supplied produce events.
    """
    def common():
        return {"creator": creator, "client": client}

    events: List[Event] = [
        CreateSubmission(**common()),
        # One event covers all three legacy columns: proxied_* become
        # submitter_name/submitter_email, proxy_name becomes proxy.
        SetProxyInformation(**common(),
                            proxied_name=metadata.contact_name,
                            proxied_email=metadata.contact_email,
                            proxy_name=depositor),
        ConfirmPolicy(**common(), agreement_id=SWORD_AGREEMENT_ID),
        SetLicense(**common(), license_uri=license_uri,
                   license_name=license_name_for(license_uri)),
        SetTitle(**common(), title=metadata.title),
        SetAbstract(**common(), abstract=metadata.summary),
        _set_authors(metadata, common()),
        SetPrimaryClassification(**common(), category=metadata.primary_category),
    ]

    events.extend(AddSecondaryClassification(**common(), category=category)
                  for category in metadata.secondary_categories)

    optional = (
        (SetComments, "comments", metadata.comments),
        (SetJournalReference, "journal_ref", metadata.journal_ref),
        (SetDOI, "doi", metadata.doi),
        (SetReportNumber, "report_num", metadata.report_num),
        (SetACMClassification, "acm_class", metadata.acm_class),
        (SetMSCClassification, "msc_class", metadata.msc_class),
    )
    for event_class, field_name, value in optional:
        if value:
            events.append(event_class(**common(), **{field_name: value}))

    return events


def _set_authors(metadata: WrapperMetadata, common: dict):
    """Authors, as a display string plus one `Author` each.

    SWORD carries free-text contributor names, not structured ones, and arXiv's
    canonical storage is a single string -- so ``authors_display`` is supplied
    directly rather than derived. Affiliations are already folded into each name
    the way ``AtomPP.pm:940-942`` does.
    """
    from submit_ce.domain.event import SetAuthors
    return SetAuthors(
        **common,
        authors=[Author(order=index, display=name)
                 for index, name in enumerate(metadata.authors)],
        authors_display=metadata.author_line,
    )


def upload_events(metadata: WrapperMetadata, store: DepositStore,
                  *, creator: User, client: Client) -> List[Event]:
    """Events that move staged deposits into the submission's workspace.

    A zip becomes `UploadArchive` so it is unpacked -- the manual recommends
    bundling TeX sources that way (``submit_sword.md:317``). Anything else is
    added as a plain file.
    """
    events: List[Event] = []
    loose: List[StagedFile] = []

    for deposit_id in metadata.media_ids:
        deposit = store.get(deposit_id)
        data = store.read(deposit_id)
        if deposit is None or data is None:
            # parse_wrapper already proved these exist; a miss here means the
            # deposit was reaped between validation and ingest.
            raise RuntimeError(f"staged deposit {deposit_id} vanished")

        staged = StagedFile(filename=f"{deposit_id}.{deposit.extension}",
                            content_type=deposit.content_type,
                            stream=io.BytesIO(data))
        if deposit.extension == "zip":
            events.append(UploadArchive(creator=creator, client=client,
                                        file=staged))
        else:
            loose.append(staged)

    if loose:
        events.append(UploadFiles(creator=creator, client=client, files=loose))
    return events


def version_row_id(session: SqlalchemySession, paper_id: str,
                   version: int) -> Optional[int]:
    """The classic row a replacement just created, by paper and version.

    ``SubmitApi.save`` reports the *original* submission id -- one domain identity
    per paper, however many rows classic holds -- so the new row's id is not in its
    return value and has to be looked up.
    """
    row = (session.query(models.Submission.submission_id)
           .filter(models.Submission.doc_paper_id == paper_id,
                   models.Submission.version == version)
           .order_by(models.Submission.submission_id.desc())
           .first())
    return int(row[0]) if row is not None else None


def record_tracking(session: SqlalchemySession, sword_id: int,
                    submission_id: int) -> None:
    """Link a deposit id to the submission row it created.

    ``submission_id`` is the row *this deposit* produced -- for a replacement the
    new version row, not the paper's original. That is what legacy did
    (``arXiv/Submit/Submission.pm:319-332`` stamps ``sword_id`` on the row it just
    created, whether ``new`` or ``rep``), and it is what makes the row a candidate
    for the worker, which selects on ``sword_id IS NOT NULL``. Pointing every
    deposit at the original instead left replacements uncompilable and overwrote
    the original's own link.

    Written synchronously so ``/resolve/app/<sword_id>`` answers as soon as the
    client has its 202. ``timestamp`` is supplied explicitly: it is NOT NULL with a
    ``FetchedValue()`` default, which MySQL fills from ``CURRENT_TIMESTAMP`` but
    sqlite has no DDL default for.
    """
    session.add(models.Tracking(
        sword_id=sword_id,
        paper_id=TRACKING_IN_PROGRESS.format(submission_id=submission_id),
        timestamp=datetime.now(timezone.utc)))
    session.flush()

    # The reverse link. arXiv_submissions.sword_id is a foreign key onto
    # arXiv_tracking.sword_id, so the tracking row has to exist first.
    row = session.get(models.Submission, submission_id)
    if row is not None:
        row.sword_id = sword_id
    session.commit()


def ingest_wrapper(api: SubmitApi,
                   store: DepositStore,
                   session: SqlalchemySession,
                   metadata: WrapperMetadata,
                   *,
                   creator: User,
                   client: Client,
                   depositor: str,
                   license_uri: str,
                   sword_id: str) -> Tuple[object, Optional[int]]:
    """Create the submission for a wrapper deposit.

    Returns the submission and its id. Every event goes through a single
    `SubmitApi.save`, so the whole deposit is one transaction: a validation failure
    anywhere leaves no partial submission.
    """
    events = metadata_events(metadata, creator=creator, client=client,
                             depositor=depositor, license_uri=license_uri)
    events.extend(upload_events(metadata, store, creator=creator, client=client))

    submission, _ = api.save(*events)
    submission_id = submission.submission_id

    # save() reports submission_id as an int while get_with_history() reports a
    # str; normalise before it reaches the database or a URL.
    record_tracking(session, int(sword_id), int(submission_id))

    logger.info("SWORD deposit %s created submission %s", sword_id, submission_id)
    return submission, int(submission_id)


def ingest_replacement(api: SubmitApi,
                       store: DepositStore,
                       session: SqlalchemySession,
                       metadata: WrapperMetadata,
                       *,
                       creator: User,
                       client: Client,
                       depositor: str,
                       license_uri: str,
                       sword_id: str,
                       submission_id: int) -> Tuple[object, int]:
    """Create the next version of an announced submission.

    A replacement is a new *version*, not a new submission
    (``submit_sword.md:711-717``), so it opens with `CreateSubmissionVersion` against
    the existing submission id rather than `CreateSubmission`.

    Classification events are omitted: arXiv does not permit the categories to
    change during a replacement (``submit_sword.md:780``), and `parse_wrapper` has
    already refused any wrapper whose categories differ (ERCTS). Re-sending them
    would trip `cannot_be_primary`/`cannot_be_secondary` against the version's own
    existing classifications.
    """
    from submit_ce.domain.event import CreateSubmissionVersion

    events: List[Event] = [CreateSubmissionVersion(creator=creator, client=client)]
    events.extend(
        event for event in metadata_events(
            metadata, creator=creator, client=client, depositor=depositor,
            license_uri=license_uri)
        if not isinstance(event, (CreateSubmission, SetPrimaryClassification,
                                  AddSecondaryClassification)))
    events.extend(upload_events(metadata, store, creator=creator, client=client))

    submission, _ = api.save(*events, submission_id=str(submission_id))

    # Track the row this deposit created, not the paper's original. save() reports
    # the original id, so the new version row is looked up by paper and version.
    new_row = version_row_id(session, submission.arxiv_id, submission.version)
    record_tracking(session, int(sword_id), new_row or submission_id)

    logger.info("SWORD deposit %s replaced submission %s as version %s (row %s)",
                sword_id, submission_id, submission.version, new_row)
    return submission, submission_id
