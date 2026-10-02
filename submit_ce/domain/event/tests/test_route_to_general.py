"""SUBMISSION-39: finalize routes a flagged submitter to a general category.

A port of legacy ``route_to_gen`` (``arXiv::Schema::Result::Submission``).
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from pytz import UTC

from submit_ce.domain import agent
from submit_ce.domain.meta import Classification
from submit_ce.domain.event import FinalizeSubmission, RouteToGeneralCategory
from submit_ce.domain.event.route_to_general import general_category
from submit_ce.domain.submission import Submission, SubmissionType


def _user():
    return agent.PublicUser(name="Test User", user_id="u1",
                            email="u1@example.org", endorsements=[])


def _submission(primary="astro-ph.GA", secondaries=(),
                submission_type=SubmissionType.NEW):
    u = _user()
    return Submission(
        creator=u, owner=u, created=datetime.now(UTC),
        primary_classification=Classification(category=primary),
        secondary_classification=[Classification(category=c) for c in secondaries],
        submission_type=submission_type)


def _routes(submission):
    events = FinalizeSubmission(creator=_user(), created=datetime.now(UTC)) \
        .consequences(submission)
    return [e for e in events if isinstance(e, RouteToGeneralCategory)]


def _route(submission, matches):
    api = MagicMock()
    api.routes_to_general_category.return_value = matches
    event = RouteToGeneralCategory(creator=agent.System(name="test"),
                                   created=datetime.now(UTC))
    event.execute(api, submission)
    api.routes_to_general_category.assert_called_once_with("u1", "u1@example.org")
    return event, event.apply(submission)


@pytest.mark.parametrize("primary, expected", [
    ("math.AG", "math.GM"),
    ("test.dis-nn", "test.mtrl-sci"),
    ("astro-ph.GA", "physics.gen-ph"),
    ("hep-th", "physics.gen-ph"),
    ("math-ph", "physics.gen-ph"),
    ("econ.GN", "physics.gen-ph"),
    ("eess.SP", "physics.gen-ph"),
    ("cs.AI", None),
    ("q-bio.GN", None),
    ("q-fin.GN", None),
    ("stat.ML", None),
])
def test_general_category(primary, expected):
    assert general_category(primary) == expected


def test_new_finalize_routes_before_anything_else():
    """Legacy routes first, so the emails that follow see the general category."""
    events = FinalizeSubmission(creator=_user(), created=datetime.now(UTC)) \
        .consequences(_submission())
    assert isinstance(events[0], RouteToGeneralCategory)


def test_only_new_submissions_are_routed():
    for sub_type in (SubmissionType.REPLACEMENT, SubmissionType.WITHDRAWAL,
                     SubmissionType.CROSS_LIST, SubmissionType.JOURNAL_REFERENCE):
        assert _routes(_submission(submission_type=sub_type)) == [], sub_type


def test_exempt_archives_are_not_routed():
    assert _routes(_submission(primary="cs.AI")) == []


def test_matching_submitter_is_routed_and_loses_secondaries():
    event, after = _route(_submission(primary="math.AG",
                                      secondaries=["math.CO", "math.NT"]), True)
    assert event.category == "math.GM"
    assert after.primary_category == "math.GM"
    assert after.secondary_categories == []


def test_other_submitters_are_left_alone():
    event, after = _route(_submission(secondaries=["astro-ph.CO"]), False)
    assert event.category is None
    assert after.primary_category == "astro-ph.GA"
    assert after.secondary_categories == ["astro-ph.CO"]
