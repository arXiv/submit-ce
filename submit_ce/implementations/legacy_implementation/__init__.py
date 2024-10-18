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
from . import db

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
        if not submission_id:
            raise NoSuchSubmission()
        if isinstance(submission_id, str) and not submission_id.isdigit():
            raise NoSuchSubmission(f"Submission {submission_id[0:20]} does not exist (legacy must use int ids)")
        stmt = select(Submission).where(Submission.submission_id == int(submission_id))
        if lock_row:  # row will be locked until .commit() use .flush() to get auto inc ids without unlocking
            stmt = stmt.with_for_update()
        submission = session.scalars(stmt).first()
        if not submission:
            raise NoSuchSubmission()
        else:
            return (to_submission(submission), [])

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
            before: Optional[Submission] = None
            existing_events: List[Event] = []
            if submission_id is not None:
                before, existing_events = self._load(session, submission_id, lock_row=True)
            elif events[0].submission_id is None and not isinstance(events[0], CreateSubmission):
                raise NoSuchSubmission('Unable to determine submission')

            committed: List[Event] = []
            for event in events:
                if event.submission_id is None and submission_id is not None:
                    event.submission_id = submission_id

                # The created timestamp should be roughly when the event was
                # committed. Since the event may refer to its own ID
                # which in future versions should be based on the creation time, this must be set before
                # the event is applied.
                event.created = datetime.now(UTC)
                logger.debug('Apply event %s: %s', event.event_id, event.NAME)
                after = event.apply(before)
                if not event.committed:
                    consequent_event, after =db.store_event(session, event, before, after)
                    committed.append(consequent_event)

                before = after  # Prepare for the next event.

            all_ = sorted(existing_events + committed, key=lambda e: e.created)
            session.commit()
            return after, list(all_)



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

