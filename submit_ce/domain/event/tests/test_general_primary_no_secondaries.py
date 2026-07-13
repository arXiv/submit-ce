"""SUBMISSION-158: a submission with a general primary category may not carry
any secondary classifications. Enforced at finalize (every submission).

Edge cases (replacement-inherited and moderator/EUST-added secondaries) are
deferred to a follow-up and are not covered here.
"""

from datetime import datetime

from pytz import UTC
import pytest

from submit_ce.domain import agent, meta
from submit_ce.domain.uploads import SourceFormat
from submit_ce.domain.event import FinalizeSubmission, InvalidEvent
from submit_ce.domain.submission import Submission, SubmissionMetadata

GENERAL_PRIMARY = "math.GM"      # is_general == True
SPECIFIC_PRIMARY = "astro-ph.GA"  # is_general == False
SECONDARY = "astro-ph.CO"


def _now():
    return datetime.now(UTC)


def _user():
    return agent.PublicUser(name="Test User", user_id="u1",
                            email="u1@example.org", endorsements=[])


def _finalizable(primary, secondaries):
    """An otherwise-finalizable submission with the given primary and
    secondary categories, so finalize can fail only on this rule."""
    u = _user()
    return Submission(
        creator=u, owner=u, created=_now(),
        source_format=SourceFormat("pdf"),
        license=meta.License(uri="http://free", name="free"),
        submitter_accepts_policy=True,
        primary_classification=meta.Classification(primary),
        secondary_classification=[meta.Classification(c) for c in secondaries],
        metadata=SubmissionMetadata(
            title="the best title",
            abstract="very abstract",
            authors_display="J K Jones, F W Englund",
        ),
    )


def _finalize():
    return FinalizeSubmission(creator=_user(), created=_now())


def test_general_primary_with_secondary_cannot_finalize():
    sub = _finalizable(GENERAL_PRIMARY, [SECONDARY])
    with pytest.raises(InvalidEvent, match="general primary category"):
        _finalize().validate_pre_lock(sub)


def test_general_primary_without_secondary_can_finalize():
    sub = _finalizable(GENERAL_PRIMARY, [])
    _finalize().validate_pre_lock(sub)  # does not raise


def test_specific_primary_with_secondary_can_finalize():
    """The rule only applies to general primaries."""
    sub = _finalizable(SPECIFIC_PRIMARY, [SECONDARY])
    _finalize().validate_pre_lock(sub)  # does not raise
