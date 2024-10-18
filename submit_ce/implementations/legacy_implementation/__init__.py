import logging
from datetime import datetime, UTC
from typing import Optional, List, Tuple, Callable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as SqlalchemySession, Session

from submit_ce.api import domain as api, SubmitApi, Event
from submit_ce.api.file_store import SubmissionFileStore
from submit_ce.implementations.file_store.legacy_file_store import LegacyFileStore
from .auth import get_user_impl
from .db import to_submission
from .models import Submission, Document, SubmissionCategory
from ...api.domain.event import CreateSubmission
from ...api.exceptions import NoSuchSubmission, NothingToDo

logger = logging.getLogger(__name__)


def check_user_authorized(session: Session, user: api.User, client: api.Client, submision_id: str) -> None:
    # TODO implement authorized check, use scopes from arxiv.auth?
    # TODO implement is_locked on submission
    pass

class LegacySubmitImplementation(SubmitApi):
    """
    Implementation of `SubmitApi` that interoperates with legacy submission by writing to SFS and DB.

    TODO write admin log on all changes
    TODO success response objects (similar to modapi? {msg: success, updated_fields:[]})
    TODO failure to validate response objects (which field caused the problem?)
    TODO Failure response object (general failure message)
    TODO Later: edit token similar to modapi?
    """

    def __init__(self,
                 store: Optional[SubmissionFileStore] = None,
                 get_session:Callable[[],SqlalchemySession] = None,
                 get_user: Callable[[],api.User] = None,
                 get_client: Callable[[], api.Client] = None,
                 serialize_file_operations:bool = False):
        self.get_user = get_user
        self.get_client = get_client
        self.get_session = get_session
        self.serialize_file_operations = serialize_file_operations

        if store is None:
            #self.store = LegacyFileStore(root_dir=legacy_specific_settings.legacy_root_dir)
            self.store = LegacyFileStore(root_dir="data/new") # for testing only
        else:
            self.store = store

    def load(self, submission_id: str) -> Tuple[Submission, List[Event]]:
        return self._load(self.get_session(), submission_id)

    def _load(self, session: SqlalchemySession, submission_id: str, lock_row: bool = False) -> Tuple[Submission, List[Event]]:
        if not submission_id or not submission_id.isdigit():
            raise NoSuchSubmission(f"Submission {submission_id[0:20]} does not exist (legacy must use int ids)")
        stmt = select(Submission).where(Submission.submission_id == int(submission_id))
        if lock_row:  # row will be locked until .commit() use .flush() to get auto inc ids without unlocking
            session.begin()
            stmt = stmt.with_for_update()
        submission = session.scalars(stmt).first()
        if not submission:
            raise NoSuchSubmission()
        else:
            return to_submission(submission)

    def load_submissions_for_user(self, user_id: str) -> List[Submission]:
        session = self.get_session()
        stmt = select(models.Submission) \
            .where(models.Submission.submitter_id == int(user_id),
                   models.Submission.status.in_([0, 1, 2, 4])) \
            .order_by(Submission.submission_id.desc())
        submissions: List[Submission] = [to_submission(row) for row in session.execute(stmt).unique().scalars().all()]
        return submissions

    def save(self, *events: Event, submission_id: Optional[int] = None) -> Tuple[Submission, List[Event]]:
        if not events:
            raise NothingToDo()
        with self.get_session() as session:
            if submission_id is not None:
                submission, existing_events = self._load(session, submission_id, lock_row=True)
            elif events[0].submission_id is None and not isinstance(events[0], CreateSubmission):
                raise NoSuchSubmission('Unable to determine submission')

            before = submission
            committed: List[Event] = []
            for event in events:
                # Fill in submission IDs, if they are missing.
                if event.submission_id is None and submission_id is not None:
                    event.submission_id = submission_id

                # The created timestamp should be roughly when the event was
                # committed. Since the event may refer to its own ID
                # which in future versions should be based on the creation time, this must be set before
                # the event is applied.
                event.created = datetime.now(UTC)
                logger.debug('Apply event %s: %s', event.event_id, event.NAME)
                after = event.apply(before)
                committed.append(event)
                if not event.committed:
                    after, consequent_events =self._store_event(session, event, before, after)
                    committed += consequent_events

                before = after  # Prepare for the next event.

            all_ = sorted(set(existing_events) | set(committed), key=lambda e: e.created)
            return after, list(all_)

    def _store_event(self, session: SqlalchemySession, event: Event, before: Optional[Submission], after: Submission,
                    *call: Callable) -> Tuple[Event, Submission]:
        """
        Store an event, and update submission state.

        This is where we map the NG event domain onto the classic database. The
        main differences are that:

        - In the event domain, a submission is a single stream of events, but
          in the classic system we create new rows in the submission database
          for things like replacements, adding DOIs, and withdrawing papers.
        - In the event domain, the only concept of the announced paper is the
          paper ID. In the classic submission database, we also have to worry about
          the row in the Document database.

        We assume that the submission states passed to this function have the
        correct paper ID and version number, if announced. The submission ID on
        the event and the before/after states refer to the original classic
        submission only.

        Parameters
        ----------
        event : :class:`Event`
        before : :class:`Submission`
            The state of the submission before the event occurred.
        after : :class:`Submission`
            The state of the submission after the event occurred.
        call : list
            Items are callables that accept args ``Event, Submission, Submission``.
            These are called within the transaction context; if an exception is
            raised, the transaction is rolled back.

        """
        # Let the caller determine the transaction scope.
        session
        if event.committed:
            raise ValueError('%s already committed', event.event_id)
        if event.created is None:
            raise ValueError('Event creation timestamp not set')
        logger.debug('store event %s', event.event_type)

        doc_id: Optional[int] = None

        # This is the case that we have a new submission.
        if before is None:  # and isinstance(after, Submission):
            dbs = models.Submission(type=models.Submission.NEW_SUBMISSION)
            dbs.update_from_submission(after)
            this_is_a_new_submission = True

        else:  # Otherwise we're making an update for an existing submission.
            this_is_a_new_submission = False

            if before.arxiv_id is not None:  #:
                # After the original submission is announced, a new Document row is
                # created. This Document is shared by all subsequent Submission rows.
                doc_id = _load_document_id(before.arxiv_id, before.version)

                # From the perspective of the database, a replacement is mainly an
                # incremented version number. This requires a new row in the
                # database.
                if after.version > before.version:
                    dbs = _create_replacement(doc_id, before.arxiv_id,
                                              after.version, after, event.created)
                elif isinstance(event, Rollback) and before.version > 1:
                    dbs = _delete_replacement(doc_id, before.arxiv_id,
                                              before.version)


                # Withdrawals also require a new row, and they use the most recent
                # version number.
                elif isinstance(event, RequestWithdrawal):
                    dbs = _create_withdrawal(doc_id, event.reason,
                                             before.arxiv_id, after.version, after,
                                             event.created)
                elif isinstance(event, RequestCrossList):
                    dbs = _create_crosslist(doc_id, event.categories,
                                            before.arxiv_id, after.version, after,
                                            event.created)

                # Adding DOIs and citation information (so-called "journal reference")
                # also requires a new row. The version number is not incremented.
                elif before.is_announced and type(event) in JREFEvents:
                    dbs = _create_jref(doc_id, before.arxiv_id, after.version, after,
                                       event.created)

                elif isinstance(event, CancelRequest):
                    dbs = _cancel_request(event, before, after)

                # The submission has been announced.
                elif isinstance(before, Submission) and before.arxiv_id is not None:
                    dbs = _load(paper_id=before.arxiv_id, version=before.version)
                    _preserve_sticky_hold(dbs, before, after, event)
                    dbs.update_from_submission(after)
                else:
                    raise TransactionFailed("Something is fishy")


            # The submission has not yet been announced; we're working with a single row.
            elif isinstance(before, Submission) and before.submission_id:
                dbs = _load(before.submission_id)

                _preserve_sticky_hold(dbs, before, after, event)
                dbs.update_from_submission(after)
            else:
                raise TransactionFailed("Something is fishy")

        db_event = _new_dbevent(event)
        session.add(dbs)
        session.add(db_event)

        # Make sure that we get a submission ID; note that this # does not commit
        # the transaction, just pushes the # SQL that we have generated so far to
        # the database # server.
        session.flush()

        log.handle(event, before, after)  # Create admin log entry.
        for func in call:
            logger.debug('call %s with event %s', func, event.event_id)
            func(event, before, after)
        if isinstance(event, AddProposal):
            assert before is not None
            proposal.add(event, before, after)

        # Attach the database object for the event to the row for the
        #  submission.
        if this_is_a_new_submission:  # Update in transaction.
            db_event.submission = dbs
        else:  # Just set the ID directly.
            assert before is not None
            db_event.submission_id = before.submission_id

        event.committed = True

        # Update the domain event and submission states with the submission ID.
        # This should carry forward the original submission ID, even if the
        # classic database has several rows for the submission (with different
        # IDs).
        if this_is_a_new_submission:
            event.submission_id = dbs.submission_id
            after.submission_id = dbs.submission_id
        else:
            assert before is not None
            event.submission_id = before.submission_id
            after.submission_id = before.submission_id
        return event, after

    #
    # def start(self, impl_data: Dict, user: api.User, client: api.Client, started: Union[StartedNew, StartedAlterExising]) -> str:
    #     session = self.get_session()
    #     now = datetime.datetime.utcnow()
    #     submission = Submission(submitter_id=user.identifier,
    #                             submitter_name=user.get_name(),
    #                             submitter_email=user.email,
    #                             userinfo=0,
    #                             agree_policy=0,
    #                             viewed=0,
    #                             stage=0,
    #                             created=now,
    #                             updated=now,
    #                             source_size=0,
    #                             allow_tex_produced=0,
    #                             is_oversize=0,
    #                             auto_hold=0,
    #                             remote_addr=client.remoteAddress,
    #                             remote_host=client.remoteHost,
    #                             type=started.submission_type,
    #                             package="",
    #                             must_process=1,
    #                             )
    #
    #     if isinstance(started, StartedAlterExising):
    #         doc = session.scalars(select(Document).where(Document.paper_id==started.paperid)).first()
    #         if not doc:
    #             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,detail="Existing paper not found.")
    #         elif doc.submitter_id != user.identifier:
    #             raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Not submitter of existing paper.")
    #         else:
    #             submission.document_id = doc.document_id
    #             submission.doc_paper_id = doc.paper_id
    #
    #     session.add(submission)
    #     session.commit()
    #     return str(submission.submission_id)
    #
    #
    # # TODO need to do "userinfo" attestation
    #
    # def accept_policy_post(self, impl_data: Dict, user: api.User, client: api.Client,
    #                              submission_id: str,
    #                              agreement: AgreedToPolicy) -> object:
    #     session = impl_data["session"]
    #     submission = check_submission_exists(session, submission_id)
    #     if agreement.accepted_policy_id != 3:
    #         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
    #                             detail=f"policy {agreement.accepted_policy_id} is not the currently accepted policy.")
    #     if submission.agree_policy == 1:
    #         return
    #     submission.agreement_id = agreement.accepted_policy_id
    #     submission.agree_policy = 1
    #     session.commit()
    #
    # def set_license_post(self, impl_data: dict, user: api.User, client: api.Client,
    #                            submission_id: str, set_license: SetLicense) -> None:
    #     session = impl_data["session"]
    #     check_user_authorized(session, user, client, submission_id)
    #     submission = check_submission_exists(session, submission_id)
    #     submission.license = set_license.license_uri
    #     session.commit()
    #
    # def assert_authorship_post(self, impl_data: Dict, user: api.User, client: api.Client,
    #                                  submission_id: str, authorship: Union[AuthorshipDirect, AuthorshipProxy]) -> str:
    #     session = impl_data["session"]
    #     check_user_authorized(session, user, client, submission_id)
    #     submission = check_submission_exists(session, submission_id)
    #     if isinstance(authorship, AuthorshipDirect):
    #         submission.is_author=1
    #     else:
    #         submission.is_author=0
    #         submission.proxy=authorship.proxy
    #     session.commit()
    #     return "success"
    #
    # def file_post(self, impl_data: Dict, user: api.User, client: api.Client, submission_id: str, uploadFile: UploadFile):
    #     session: SqlalchemySession = impl_data["session"]
    #     check_user_authorized(session, user, client, submission_id)
    #     submission = check_submission_exists(session, submission_id,
    #                                          lock_row=legacy_specific_settings.legacy_serialize_file_operations)
    #     acceptable_types = ["application/gzip", "application/tar", "application/tar+gzip"]
    #     if uploadFile.content_type in acceptable_types:
    #         checksum = self.store.store_source_package(submission.submission_id, uploadFile)
    #
    #     # TODO db changes for upload: source_format
    #     # TODO db changes for upload: source_size
    #     # TODO db changes for upload: package?
    #
    #     else:
    #         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
    #                             detail="File content type must be one of {acceptable_types}"\
    #                             " but it was {uploadFile.content_type}."
    #                             )
    #
    # def set_categories_post(self, impl_data: Dict, user: api.User, client: api.Client, submission_id: str,
    #                               data: SetCategories):
    #     session: SqlalchemySession = impl_data["session"]
    #     check_user_authorized(session, user, client, submission_id)
    #     submission = check_submission_exists(session, submission_id)
    #
    #     # similar to code in modapi routes.py
    #     stmt = select(SubmissionCategory).where(SubmissionCategory.submission_id == submission.submission_id)
    #     early_rows = session.scalars(stmt).all()
    #     early_primary = next((c.category for c in early_rows if c.is_primary), None)
    #     early_categories = set(c.category for c in early_rows)
    #
    #     new_primary = data.primary_category
    #     new_secondaries = set(data.secondary_categories)
    #     new_categories = new_secondaries.copy()
    #     if new_primary:
    #         new_categories.add(new_primary)
    #
    #     add_categories = new_categories - early_categories
    #     del_categories = early_categories - new_categories
    #
    #     updates = set()
    #     for cat in add_categories:
    #         if cat == new_primary:
    #             updates.add("primary")
    #         else:
    #             updates.add("secondary")
    #         session.add(SubmissionCategory(
    #             submission_id=submission.submission_id,
    #             category=cat,
    #             is_primary=cat == new_primary,
    #             is_published=0,
    #         ))
    #
    #     for cat in del_categories:
    #         if cat == new_primary:
    #             updates.add("primary")
    #         else:
    #             updates.add("secondary")
    #         row = [row for row in early_rows if row.category == cat]
    #         session.delete(row[0])
    #
    #     if updates:
    #         session.commit()
    #         #self.admin_log(session, user, f"Edited: {','.join(updates)}", command="edit metadata")
    #
    #     result = CategoryChange()
    #     eps = set() if not early_primary else set([early_primary])
    #     if early_primary != new_primary:
    #         result.old_primary = early_primary
    #         result.new_primary = new_primary
    #     if new_secondaries != early_categories - eps:
    #         result.old_secondaries = list(early_categories - eps)
    #         result.new_secondaries = list(new_categories)
    #     return result
    #
    # def set_metadata_post(self, impl_data: Dict, user: api.User, client: api.Client, submission_id: str,
    #                             metadata: Union[SetMetadata]):
    #     session: SqlalchemySession = impl_data["session"]
    #     check_user_authorized(session, user, client, submission_id)
    #     submission = check_submission_exists(session, submission_id)
    #     update = []
    #     # TODO add checks
    #     if metadata.abstract != submission.abstract:
    #         submission.abstract = metadata.abstract
    #         update.append("abstract")
    #     if metadata.authors != submission.authors:
    #         submission.authors = metadata.authors
    #         update.append("authors")
    #     if metadata.title != submission.title:
    #         submission.title = metadata.title
    #         update.append("title")
    #     if metadata.comments != submission.comments:
    #         submission.comments = metadata.comments
    #         update.append("comments")
    #     if metadata.acm_class != submission.acm_class:
    #         submission.acm_class = metadata.acm_class
    #         update.append("acm_class")
    #     if metadata.msc_class != submission.msc_class:
    #         submission.msc_class = metadata.msc_class
    #         update.append("msc_class")
    #     if metadata.report_num != submission.report_num:
    #         submission.report_num = metadata.report_num
    #         update.append("report_num")
    #     if metadata.journal_ref != submission.journal_ref:
    #         submission.journal_ref = metadata.journal_ref
    #         update.append("journal_ref")
    #     if metadata.doi != submission.doi:
    #         submission.doi = metadata.doi
    #         update.append("doi")
    #
    #     """Why is does it let blank fields in metadata?
    #      Because those whill be handled by workflows and conditions.
    #      (Or folks will tell us "absolutely no partial metadata! and we'll change this)"""
    #
    #     if update:
    #         # TODO Write admin_log
    #         session.commit()
    #
    #     return ",".join(update)
    #
    # def verify_user_post(self, impl_data: Dict, user: User, client: Client, submission_id: str, verifyUser: VerifyUser):
    #     # session: SqlalchemySession = impl_data["session"]
    #     # check_user_authorized(session, user, client, submission_id)
    #     # submission = check_submission_exists(session, submission_id)
    #     # TODO legacy lacks a concept of "users has verified their info"
    #     pass
    #
    # def mark_deposited_post(self, impl_data: Dict, user: api.User, client: api.Client, submission_id: str) -> None:
    #     pass
    #
    # def mark_processing_for_deposit_post(self, impl_data: Dict, user: api.User, client: api.Client, submission_id: str) -> None:
    #     pass
    #
    # def unmark_processing_for_deposit_post(self, impl_data: Dict, user: api.User, client: api.Client, submission_id: str) -> None:
    #     pass


    def get_service_status(self, impl_data: dict):
        return f"{self.__class__.__name__}  impl_data: {impl_data}"

