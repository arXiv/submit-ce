from arxiv.db import Session
import pytest

import arxiv.db.models as classic
from sqlalchemy import desc, select

from submit_ce.api.domain import Author, SubmissionContent
from submit_ce.api.domain.agent import InternalClient
from submit_ce.api.domain.event import (
    SetPrimaryClassification,
    CreateSubmission,
    ConfirmContactInformation,
    ConfirmAuthorship,
    SetLicense,
    ConfirmPolicy,
    SetUploadPackage,
    SetTitle,
    SetAbstract,
    SetComments,
    SetReportNumber,
    SetAuthors,
    FinalizeSubmission,
)
from submit_ce.ui.backend import api



@pytest.fixture(scope="function")
def submitted_submission(app, authorized_user):
    """A submitted submission."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        # Create a finalized submission.
        ua = InternalClient(name=f"test_client_{__file__}")
        cc0 = "http://creativecommons.org/publicdomain/zero/1.0/"
        submission, _ = api.save(
            CreateSubmission(creator=user, client=ua),
            ConfirmContactInformation(creator=user, client=ua),
            ConfirmAuthorship(creator=user, client=ua, submitter_is_author=True),
            SetLicense(creator=user, client=ua, license_uri=cc0, license_name="CC0 1.0"),
            ConfirmPolicy(creator=user, client=ua),
            SetPrimaryClassification(creator=user, client=ua, category="astro-ph.GA"),
            SetUploadPackage(creator=user, client=ua,
                checksum="a9s9k342900skks03330029k",
                source_format=SubmissionContent.Format.TEX,
                identifier="123",
                uncompressed_size=593992,
                compressed_size=59392,
            ),
            SetTitle(creator=user, client=ua, title="foo title, submitted submission"),
            SetAbstract(creator=user, client=ua, abstract="foo abstract {__file__}"),
            SetComments(creator=user, client=ua, comments="pickels"),
            SetReportNumber(creator=user, client=ua, report_num="the number 13"),
            SetAuthors(creator=user, client=ua,
                authors=[
                    Author(
                        order=0,
                        forename="Bob",
                        surname="Paulson",
                        email="Robert.Paulson@nowhere.edu",
                        affiliation="Fight Club",
                    )
                ],
            ),
            FinalizeSubmission(creator=user, client=ua),
        )
        return submission

        
@pytest.fixture(scope="function")
def published_submission(app, authorized_user):
    """A published submission."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        # Create a finalized submission.
        ua = InternalClient(name=f"test_client_{__file__}")
        cc0 = "http://creativecommons.org/publicdomain/zero/1.0/"
        submission, _ = api.save(
            CreateSubmission(creator=user, client=ua),
            ConfirmContactInformation(creator=user, client=ua),
            ConfirmAuthorship(creator=user, client=ua, submitter_is_author=True),
            SetLicense(
                creator=user, client=ua, license_uri=cc0, license_name="CC0 1.0"
            ),
            ConfirmPolicy(creator=user, client=ua),
            SetPrimaryClassification(creator=user, client=ua, category="astro-ph.GA"),
            SetUploadPackage(
                creator=user,
                client=ua,
                checksum="a9s9k342900skks03330029k",
                source_format=SubmissionContent.Format.TEX,
                identifier="123",
                uncompressed_size=593992,
                compressed_size=59392,
            ),
            SetTitle(creator=user, client=ua, title="foo title"),
            SetAbstract(creator=user, client=ua, abstract="ab stract" * 20),
            SetComments(creator=user, client=ua, comments="indeed"),
            SetReportNumber(creator=user, client=ua, report_num="the number 12"),
            SetAuthors(
                creator=user,
                client=ua,
                authors=[
                    Author(
                        order=0,
                        forename="Bob",
                        surname="Paulson",
                        email="Robert.Paulson@nowhere.edu",
                        affiliation="Fight Club",
                    )
                ],
            ),
            FinalizeSubmission(creator=user, client=ua),
        )

        # announced the submission
        with Session() as session:
            maxid=session.execute(select(classic.Document.paper_id)
                                .order_by(desc(classic.Document.paper_id))
                                .limit(1)).first()
            if maxid and maxid[0]:
                yymm, monthid = maxid[0].split(".")
                paper_id = f"{yymm}.{int(monthid)+1}"
            else:
                paper_id = "1234.56789"

            db_submission = session.query(classic.Submission).get(submission.submission_id)
            if not db_submission:
                raise RuntimeError(f"No db row for {submission.submission_id}")
            db_submission.status = 7  # published
            db_submission.paper_id = paper_id
            db_document = classic.Document(
                paper_id=paper_id,
                title=submission.metadata.title,
                submitter_email=submission.creator.email,
                # submitter=submission.creator.user_id,
            )
            db_submission.doc_paper_id = paper_id
            db_submission.document = db_document
            session.add(db_submission)
            session.add(db_document)
            session.commit()
            return api.get(str(submission.submission_id)), paper_id
