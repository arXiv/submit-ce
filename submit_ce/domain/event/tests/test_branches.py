# Minimal branch-coverage tests for event creation and validation.

from datetime import datetime
from pytz import UTC
import pytest


from submit_ce.domain import submission as submod, agent, meta
from submit_ce.domain.uploads import SourceFormat
from submit_ce.domain.event import (
    make_event,              # <- alias to base.event_factory
    FinalizeSubmission,      # used directly to hit validation error
    Announce,                # simple project() path
    InvalidEvent,            # domain exception
)


def _now():
    # Keep consistent with existing tests that use pytz.UTC
    return datetime.now(UTC)


def _user(u="u1"):
    # PublicUser requires: name, user_id, email.
    # endorsements defaults to [] if not provided.
    return agent.PublicUser(
        name="Test User",
        user_id=u,
        email=f"{u}@example.org",
        endorsements=[],
    )


def test_create_submission_round_trip():
    """CreateSubmission via factory; apply(None) creates a new Submission."""
    creator = _user("alice")
    ev = make_event("CreateSubmission", created=_now(), creator=creator)
    after = ev.apply(None)  # special-case: creation works with submission=None
    assert after.creator == creator
    assert after.owner == creator
    # ID may be None pre-persist; just assert it’s stable/typed if present.
    assert after.submission_id is None or isinstance(after.submission_id, str)


def test_finalize_submission_missing_required_fields_raises():
    """FinalizeSubmission should raise when required fields are missing."""
    creator = _user("bob")
    sub = submod.Submission(creator=creator, owner=creator, created=_now())
    ev = FinalizeSubmission(creator=creator, created=_now())
    with pytest.raises(InvalidEvent):
        ev.apply(sub)


def _finalizable_submission_without_primary(creator):
    """A submission with every ``FinalizeSubmission.REQUIRED`` field present
    EXCEPT ``primary_classification``, so finalize can fail only on the
    missing primary category."""
    return submod.Submission(
        creator=creator, owner=creator, created=_now(),
        source_format=SourceFormat("pdf"),
        license=meta.License(uri="http://free", name="free"),
        submitter_accepts_policy=True,
        metadata=submod.SubmissionMetadata(
            title="the best title",
            abstract="very abstract",
            authors_display="J K Jones, F W Englund",
        ),
    )


def test_finalize_raises_when_primary_classification_missing():
    """SUBMISSION-159: a submission with no primary category cannot be
    finalized. The submission is otherwise complete, so the missing primary
    classification is the sole cause of failure."""
    creator = _user("erin")
    sub = _finalizable_submission_without_primary(creator)
    assert sub.primary_classification is None
    ev = FinalizeSubmission(creator=creator, created=_now())
    with pytest.raises(InvalidEvent, match="Missing primary_classification"):
        ev.validate_pre_lock(sub)

    # Positive control: adding a primary category lets finalize validation
    # pass, proving the missing primary was the only thing blocking submission.
    sub.primary_classification = meta.Classification("astro-ph.GA")
    ev.validate_pre_lock(sub)  # does not raise


def test_announce_sets_status_and_id():
    """Announce.project sets status to ANNOUNCED and arxiv_id to provided value."""
    creator = _user("carol")
    # A minimal submission that is not yet announced
    sub = submod.Submission(creator=creator, owner=creator, created=_now())
    # The versions field is commented out in Submission while Announce appends
    # to it. [FIX ME]
    sub.versions = []

    ev = Announce(creator=creator, created=_now(), arxiv_id="2501.01234")
    after = ev.apply(sub)
    assert after.status == submod.Submission.ANNOUNCED
    assert after.arxiv_id == "2501.01234"


def test_factory_unknown_type_raises_runtime_error():
    """Factory should error with an unknown event type name."""
    with pytest.raises(RuntimeError):
        make_event("NoSuchEventType", created=_now(), creator=_user("dave"))
