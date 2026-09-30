"""``update_from_submission`` keeps the category rows in step with the submission."""
from datetime import datetime, timezone

from submit_ce.domain import Submission as DomainSubmission
from submit_ce.domain.agent import HttpClient, PublicUser
from submit_ce.domain.meta import Classification
from submit_ce.implementations.legacy_implementation import models


def test_all_removed_secondaries_are_dropped():
    """SUBMISSION-39 drops every secondary in one event."""
    submitter = PublicUser(user_id="123", name="Rikki-tikki-tavi",
                           email="rikki@example.org")
    submission = DomainSubmission(
        creator=submitter, owner=submitter,
        client=HttpClient(remote_addr="127.0.0.1"),
        primary_classification=Classification(category="astro-ph.GA"),
        created=datetime(2026, 1, 1, tzinfo=timezone.utc))
    dbs = models.Submission(type=models.Submission.NEW_SUBMISSION, version=1,
                            categories=[
        models.SubmissionCategory(category="astro-ph.GA", is_primary=1),
        models.SubmissionCategory(category="astro-ph.CO", is_primary=0),
        models.SubmissionCategory(category="gr-qc", is_primary=0)])

    dbs.update_from_submission(submission)

    assert [c.category for c in dbs.categories] == ["astro-ph.GA"]
