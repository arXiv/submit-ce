"""Deposit tracking: what happened to a SWORD deposit.

Ports ``arxiv-submit/lib/arXiv/Controller/Sword.pm:23-103``. A wrapper deposit's
202 response carries a ``rel="alternate"`` link to ``/resolve/app/<sword_id>``, and
this is what answers it (``submit_sword.md:637-706``).

**No authentication.** ``sword.conf`` puts ``/sword-app`` and ``/ppw`` behind basic
auth but not ``/resolve`` -- it is served by the Catalyst app, and the manual
documents it as a plain GET (``submit_sword.md:664``). Reproduced as-is; note this
means deposit status is world-readable to anyone who can guess a deposit id.

The state machine keys off ``arXiv_tracking.paper_id``, which is overloaded:
``submit/<id>`` while in the workflow, the real paper id once announced, or a string
containing ``failed``.
"""

import base64
import logging
from dataclasses import dataclass
from typing import Optional

import arxiv.db.models as models
from lxml import etree
from sqlalchemy.orm import Session as SqlalchemySession

logger = logging.getLogger(__name__)

CONTENT_TYPE = 'application/xml; charset="utf-8"'
"""Verbatim from ``Controller/Sword.pm:102``, quoted charset included."""

IN_PROGRESS_PREFIX = "submit/"
FAILED_MARKER = "failed"

# The five statuses the manual defines (``submit_sword.md:686-706``).
SUBMITTED = "submitted"
PUBLISHED = "published"
ON_HOLD = "on hold"
INCOMPLETE = "incomplete"
UNKNOWN = "unknown"

FAILED = "failed"
"""A sixth status legacy actually emits (``Controller/Sword.pm:49-52``).

Undocumented -- the manual lists five. Reproduced because a client that has seen it
in the wild may switch on it.
"""

# Error strings, verbatim from Controller/Sword.pm.
NO_SUCH_DEPOSIT = ("identifier does not correspond to a SWORD wrapper, "
                   "it may belong to a media deposit")
SUBMISSION_NOT_FOUND = "Submission not found"
CONFLICTING_SUBMISSION = "conflicting submission active"
NO_DOCUMENT = "No valid document found. Please contact arXiv admins."


@dataclass(frozen=True)
class DepositStatus:
    """The state of one deposit, as reported to a depositor."""

    tracking_id: str
    status: str
    submission_id: Optional[int] = None
    arxiv_id: Optional[str] = None
    error: Optional[str] = None
    autotex_log_b64: Optional[str] = None


def tracking_uri(sword_id: int, base_url: str) -> str:
    """The tracking URI, which is also echoed inside the document.

    Built from the request's own scheme and host, so it matches the
    ``rel="alternate"`` link the wrapper response handed out.
    """
    return f"{base_url}/resolve/app/{sword_id}"


def _status_for(submission) -> str:
    """Map a submit-ce submission onto a SWORD status string.

    ``on hold`` wins over ``submitted``: a held submission is still SUBMITTED in
    submit-ce's model, with the hold recorded separately
    (`Submission.is_on_hold`).

    ``incomplete`` covers a submission still being worked on. The manual says it is
    "not expected to be used for SWORD submissions" (``submit_sword.md:700-702``)
    and that holds here: a deposit is created with its metadata complete. It can
    still appear between the 202 and a successful compile, since finalization waits
    on preflight.
    """
    if submission.is_announced:
        return PUBLISHED
    if submission.is_on_hold:
        return ON_HOLD
    if submission.is_finalized:
        return SUBMITTED
    return INCOMPLETE


def _compile_log(api, submission_id: int) -> Optional[str]:
    """Base64 of the compile log, if there is one.

    An undocumented extension: legacy attaches ``autotex.log`` (or
    ``gcp_compile.log``) as ``autotex_log_b64``
    (``Controller/Sword.pm:36-56``). Best-effort, like the Perl, which wraps the
    read in a try/catch and simply omits the field on failure.
    """
    try:
        store = api.get_file_store()
        if not store.does_compile_log_exist(str(submission_id)):
            return None
        data = store.get_compile_log(str(submission_id)).open("rb").read()
        return base64.b64encode(data).decode("ascii")
    except Exception:  # noqa: BLE001 - tracking must not fail over a log
        logger.warning("could not read compile log for submission %s",
                       submission_id, exc_info=True)
        return None


def resolve_deposit(session: SqlalchemySession, api, sword_id: int,
                    base_url: str) -> DepositStatus:
    """Look up what became of a deposit.

    Follows ``Controller/Sword.pm:25-95``: no tracking row at all is ``unknown``
    with an explanatory error, since the id may name a *media* deposit rather than a
    wrapper.
    """
    uri = tracking_uri(sword_id, base_url)

    tracking = session.query(models.Tracking).filter_by(
        sword_id=sword_id).one_or_none()
    if tracking is None:
        return DepositStatus(tracking_id=uri, status=UNKNOWN,
                             error=NO_SUCH_DEPOSIT)

    paper_id = tracking.paper_id or ""

    if paper_id.startswith(IN_PROGRESS_PREFIX):
        submission_id = paper_id[len(IN_PROGRESS_PREFIX):]
        try:
            submission = api.get(submission_id)
        except Exception:  # noqa: BLE001 - report it, do not propagate
            logger.info("tracking %s: no submission %s", sword_id, submission_id)
            return DepositStatus(tracking_id=uri, status=UNKNOWN,
                                 error=SUBMISSION_NOT_FOUND)
        return DepositStatus(
            tracking_id=uri,
            status=_status_for(submission),
            submission_id=int(submission_id),
            arxiv_id=submission.arxiv_id,
            autotex_log_b64=_compile_log(api, int(submission_id)),
        )

    if FAILED_MARKER in paper_id:
        return DepositStatus(tracking_id=uri, status=FAILED,
                             error=CONFLICTING_SUBMISSION)

    document = session.query(models.Document).filter_by(
        paper_id=paper_id).one_or_none()
    if document is None:
        return DepositStatus(tracking_id=uri, status=UNKNOWN, error=NO_DOCUMENT)
    return DepositStatus(tracking_id=uri, status=PUBLISHED, arxiv_id=paper_id)


def render_deposit(status: DepositStatus) -> bytes:
    """Serialize a `DepositStatus` as the ``<deposit>`` document.

    Element order is fixed here. Legacy iterates a Perl hash with ``each``
    (``Controller/Sword.pm:96-100``), so its order is arbitrary and varies between
    responses -- no client can depend on it, which makes a stable order strictly
    safer.
    """
    root = etree.Element("deposit")

    fields = (
        ("tracking_id", status.tracking_id),
        ("status", status.status),
        ("submission_id", status.submission_id),
        ("arxiv_id", status.arxiv_id),
        ("error", status.error),
        ("autotex_log_b64", status.autotex_log_b64),
    )
    for name, value in fields:
        if value is not None:
            etree.SubElement(root, name).text = str(value)

    return etree.tostring(root, xml_declaration=True, encoding="utf-8",
                          pretty_print=True)
