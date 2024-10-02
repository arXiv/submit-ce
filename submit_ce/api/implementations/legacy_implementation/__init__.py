import datetime
import logging
import os
from itertools import groupby
from operator import attrgetter
from typing import Dict, Union, Optional, List

import arxiv.db
from arxiv.config import settings
from fastapi import Depends, HTTPException, status, UploadFile
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session as SqlalchemySession, Session

from submit_ce.api import domain as api, domain
from ...domain.meta import CategoryChange
from submit_ce.api.domain.events import AgreedToPolicy, StartedNew, StartedAlterExising, SetLicense, \
    AuthorshipDirect, AuthorshipProxy, SetCategories, SetMetadata
from submit_ce.api.file_store import SubmissionFileStore
from submit_ce.api.file_store.legacy_file_store import LegacyFileStore
from submit_ce.api.implementations import ImplementationConfig
from submit_ce.api.implementations.default_api_base import BaseDefaultApi
from .auth import get_user_impl
from .load import to_submission
from .models import Submission, Document, SubmissionCategory

logger = logging.getLogger(__name__)

_setup = False

class LegacySpecificSettings(BaseSettings):
    legacy_data_new_prefix: str = "/data/new"
    """Where to store the files. Ex. /data/new"""

    legacy_serialize_file_operations: bool = True
    """Whether to lock on submission table row to serialize file write operations.
    
    Not serializing will expose the system to race conditions between different clients writing to the files.
    
    This will only prevent race conditions between other systems that use the row lock to exclusively write the files.
    
    Serializing will increase lock contention. """

    legacy_root_dir: str = "data/new"



legacy_specific_settings = LegacySpecificSettings(_case_sensitive=False)

def db_lock_capable(session: SqlalchemySession) -> bool:
    return "sqlite" not in session.get_bind().url

def get_session() -> SqlalchemySession:
    """Dependency for api routes"""
    global _setup
    if not _setup:
        from submit_ce.api.config import config as api_settings
        settings.CLASSIC_DB_URI = api_settings.CLASSIC_DB_URI
        if 'sqlite' in settings.CLASSIC_DB_URI:
            args = {"check_same_thread": False}
        else:   # pragma: no cover
            args = {}
        engine = create_engine(settings.CLASSIC_DB_URI, echo=settings.ECHO_SQL, connect_args=args)
        arxiv.db.session_factory = sessionmaker(autoflush=False, bind=engine)
        #configure_db_engine(engine, None)

    with arxiv.db.session_factory() as session:
        try:
            yield session
            if session.begin or session.dirty or session.deleted:
                session.commit()
                session.close()
        except Exception:
            session.rollback()
            session.close()
            raise


def legacy_depends(db=Depends(get_session)) -> dict:
    return {"session": db}

def check_user_authorized(session: Session, user: api.User, client: api.Client, submision_id: str) -> None:
    # TODO implement authorized check, use scopes from arxiv.auth?
    # TODO implement is_locked on submission
    pass

def check_submission_exists(session: Session, submission_id: str, lock_row: bool = False) -> Submission:
    try:
        stmt = select(Submission).where(Submission.submission_id == int(submission_id))
        if lock_row:  # row will be locked until .commit() use .flush() to get auto inc ids without unlocking
            session.begin()
            stmt = stmt.with_for_update()

        submission = session.scalars(stmt).first()
        if not submission:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"Submission {submission_id} does not exist")
        else:
            return submission
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Submission {submission_id} does not exist (legacy must use int ids)")


class LegacySubmitImplementation(BaseDefaultApi):
    """
    TODO write admin log on all changes
    TODO success response objects (similar to modapi? {msg: success, updated_fields:[]})
    TODO failure to validate response objects (which field caused the problem?)
    TODO Failure response object (general failure message)
    TODO Later: edit token similar to modapi?

    """

    def __init__(self, store: Optional[SubmissionFileStore] = None):
        if store is None:
            #self.store = LegacyFileStore(root_dir=legacy_specific_settings.legacy_root_dir)
            self.store = LegacyFileStore(root_dir="data/new") # for testing only
        else:
            self.store = store

    def get_submission(self, impl_data: Dict, user: api.User, client: api.Client,
                             submission_id: str) -> Submission:
        session = impl_data["session"]
        submission = check_submission_exists(session, submission_id)
        return to_submission(submission)
        #return {c.name: getattr(submission, c.name) for c in Submission.__table__.columns}


    def start(self, impl_data: Dict, user: api.User, client: api.Client, started: Union[StartedNew, StartedAlterExising]) -> str:
        session = impl_data["session"]
        now = datetime.datetime.utcnow()
        submission = Submission(submitter_id=user.identifier,
                                submitter_name=user.get_name(),
                                submitter_email=user.email,
                                userinfo=0,
                                agree_policy=0,
                                viewed=0,
                                stage=0,
                                created=now,
                                updated=now,
                                source_size=0,
                                allow_tex_produced=0,
                                is_oversize=0,
                                auto_hold=0,
                                remote_addr=client.remoteAddress,
                                remote_host=client.remoteHost,
                                type=started.submission_type,
                                package="",
                                must_process=1,
                                )

        if isinstance(started, StartedAlterExising):
            doc = session.scalars(select(Document).where(Document.paper_id==started.paperid)).first()
            if not doc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,detail="Existing paper not found.")
            elif doc.submitter_id != user.identifier:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Not submitter of existing paper.")
            else:
                submission.document_id = doc.document_id
                submission.doc_paper_id = doc.paper_id

        session.add(submission)
        session.commit()
        return str(submission.submission_id)


    # TODO need to do "userinfo" attestation

    def accept_policy_post(self, impl_data: Dict, user: api.User, client: api.Client,
                                 submission_id: str,
                                 agreement: AgreedToPolicy) -> object:
        session = impl_data["session"]
        submission = check_submission_exists(session, submission_id)
        if agreement.accepted_policy_id != 3:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"policy {agreement.accepted_policy_id} is not the currently accepted policy.")
        if submission.agree_policy == 1:
            return
        submission.agreement_id = agreement.accepted_policy_id
        submission.agree_policy = 1
        session.commit()

    def set_license_post(self, impl_dep: dict, user: api.User, client: api.Client,
                               submission_id: str, set_license: SetLicense) -> None:
        session = impl_dep["session"]
        check_user_authorized(session, user, client, submission_id)
        submission = check_submission_exists(session, submission_id)
        submission.license = set_license.license_uri
        session.commit()

    def assert_authorship_post(self, impl_dep: Dict, user: api.User, client: api.Client,
                                     submission_id: str, authorship: Union[AuthorshipDirect, AuthorshipProxy]) -> str:
        session = impl_dep["session"]
        check_user_authorized(session, user, client, submission_id)
        submission = check_submission_exists(session, submission_id)
        if isinstance(authorship, AuthorshipDirect):
            submission.is_author=1
        else:
            submission.is_author=0
            submission.proxy=authorship.proxy
        session.commit()
        return "success"

    def file_post(self, impl_dep: Dict, user: api.User, client: api.Client, submission_id: str, uploadFile: UploadFile):
        session: SqlalchemySession = impl_dep["session"]
        check_user_authorized(session, user, client, submission_id)
        submission = check_submission_exists(session, submission_id,
                                             lock_row=legacy_specific_settings.legacy_serialize_file_operations)
        acceptable_types = ["application/gzip", "application/tar", "application/tar+gzip"]
        if uploadFile.content_type in acceptable_types:
            checksum = self.store.store_source_package(submission.submission_id, uploadFile)

        # TODO db changes for upload: source_format
        # TODO db changes for upload: source_size
        # TODO db changes for upload: package?

        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="File content type must be one of {acceptable_types}"\
                                " but it was {uploadFile.content_type}."
                                )

    def set_categories_post(self, impl_dep: Dict, user: api.User, client: api.Client, submission_id: str,
                                  data: SetCategories):
        session: SqlalchemySession = impl_dep["session"]
        check_user_authorized(session, user, client, submission_id)
        submission = check_submission_exists(session, submission_id)

        # similar to code in modapi routes.py
        stmt = select(SubmissionCategory).where(SubmissionCategory.submission_id == submission.submission_id)
        early_rows = session.scalars(stmt).all()
        early_primary = next((c.category for c in early_rows if c.is_primary), None)
        early_categories = set(c.category for c in early_rows)

        new_primary = data.primary_category
        new_secondaries = set(data.secondary_categories)
        new_categories = new_secondaries.copy()
        if new_primary:
            new_categories.add(new_primary)

        add_categories = new_categories - early_categories
        del_categories = early_categories - new_categories

        updates = set()
        for cat in add_categories:
            if cat == new_primary:
                updates.add("primary")
            else:
                updates.add("secondary")
            session.add(SubmissionCategory(
                submission_id=submission.submission_id,
                category=cat,
                is_primary=cat == new_primary,
                is_published=0,
            ))

        for cat in del_categories:
            if cat == new_primary:
                updates.add("primary")
            else:
                updates.add("secondary")
            row = [row for row in early_rows if row.category == cat]
            session.delete(row[0])

        # if updates:
        #       self.admin_log(session, user, f"Edited: {','.join(updates)}", command="edit metadata")

        result = CategoryChange()
        eps = set() if not early_primary else set([early_primary])
        if early_primary != new_primary:
            result.old_primary = early_primary
            result.new_primary = new_primary
        if new_secondaries != early_categories - eps:
            result.old_secondaries = list(early_categories - eps)
            result.new_secondaries = list(new_categories)
        return result

    def set_metadata_post(self, impl_dep: Dict, user: api.User, client: api.Client, submission_id: str,
                                metadata: Union[SetMetadata]):
        session: SqlalchemySession = impl_dep["session"]
        check_user_authorized(session, user, client, submission_id)
        submission = check_submission_exists(session, submission_id)
        update = []
        # TODO add checks
        if metadata.abstract != submission.abstract:
            submission.abstract = metadata.abstract
            update.append("abstract")
        if metadata.authors != submission.authors:
            submission.authors = metadata.authors
            update.append("authors")
        if metadata.title != submission.title:
            submission.title = metadata.title
            update.append("title")
        if metadata.comments != submission.comments:
            submission.comments = metadata.comments
            update.append("comments")
        if metadata.acm_class != submission.acm_class:
            submission.acm_class = metadata.acm_class
            update.append("acm_class")
        if metadata.msc_class != submission.msc_class:
            submission.msc_class = metadata.msc_class
            update.append("msc_class")
        if metadata.report_num != submission.report_num:
            submission.report_num = metadata.report_num
            update.append("report_num")
        if metadata.journal_ref != submission.journal_ref:
            submission.journal_ref = metadata.journal_ref
            update.append("journal_ref")
        if metadata.doi != submission.doi:
            submission.doi = metadata.doi
            update.append("doi")

        """Why is does it let blank fields in metadata?
         Because those whill be handled by workflows and conditions.
         (Or folks will tell us "absolutely no partial metadata! and we'll change this)"""

        if update:
            # TODO Write admin_log
            session.commit()

        return ",".join(update)

    def mark_deposited_post(self, impl_data: Dict, user: api.User, client: api.Client, submission_id: str) -> None:
        pass

    def mark_processing_for_deposit_post(self, impl_data: Dict, user: api.User, client: api.Client, submission_id: str) -> None:
        pass

    def unmark_processing_for_deposit_post(self, impl_data: Dict, user: api.User, client: api.Client, submission_id: str) -> None:
        pass


    def get_service_status(self, impl_data: dict):
        return f"{self.__class__.__name__}  impl_data: {impl_data}"

    def user_submissions(self, impl_data: dict,
                               user: api.User, client: api.Client) -> List[Submission]:
        # TODO Write a test for this
        session = impl_data["session"]
        user.identifier
        stmt = select(models.Submission)\
            .where(models.Submission.submitter_id == int(user.identifier),
                   models.Submission.status.in_([ 0, 1, 2, 4 ]))\
            .order_by(Submission.submission_id.desc())
        submissions: List[Submission] = [to_submission(row) for row in session.execute(stmt).unique().scalars().all()]
        return submissions


def setup(settings: BaseSettings) -> None:
    pass


implementation = ImplementationConfig(
    impl=LegacySubmitImplementation(),
    depends_fn=legacy_depends,
    setup_fn=setup,
    userid_to_user=get_user_impl,
)

