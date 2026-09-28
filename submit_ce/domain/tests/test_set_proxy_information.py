"""Tests for the ``SetProxyInformation`` domain event.

The proxy submission feature lets an approved submitter (the *proxy*) submit
on behalf of someone else (the *proxied* contact). When the event is applied
to a :class:`.Submission`, three things must happen:

* ``submission.creator.name`` is overwritten with ``proxied_name``.
* ``submission.creator.email`` is overwritten with ``proxied_email``.
* ``submission.proxy`` is set to the ``proxy_name`` string.

The legacy DB schema stores the contact name/email in the ``submitter_name``/
``submitter_email`` columns, which is why the event mutates ``creator`` rather
than introducing a separate field. ``submission.proxy`` is a free-form string
flagging that the submission was proxied.
"""
import pytest
from arxiv.auth.auth import scopes

from submit_ce.domain import Submission
from submit_ce.domain.agent import PublicUser
from submit_ce.domain.event import SetProxyInformation
from submit_ce.domain.exceptions import InvalidEvent


def _make_submitter() -> PublicUser:
    return PublicUser(
        user_id="123",
        name="David Submitter",
        email="david@example.org",
        scopes=[scopes.PROXY_SUBMISSION],
    )


def _make_submission(submitter: PublicUser) -> Submission:
    """Build a minimal Submission owned by ``submitter`` with no proxy set."""
    return Submission(creator=submitter, owner=submitter)


def test_apply_rejects_a_creator_who_may_not_proxy():
    """Verify User and SWORD check this too, but both go through the event."""
    submitter = _make_submitter()
    submitter.scopes = []

    event = SetProxyInformation(
        creator=submitter,
        proxied_name="Bob Proxied",
        proxied_email="bob@proxied.org",
        proxy_name="David Submitter",
    )

    with pytest.raises(InvalidEvent):
        event.apply(_make_submission(submitter))


def test_apply_overwrites_creator_name_and_email():
    submitter = _make_submitter()
    submission = _make_submission(submitter)

    event = SetProxyInformation(
        creator=submitter,
        proxied_name="Bob Proxied",
        proxied_email="bob@proxied.org",
        proxy_name="David Submitter",
    )

    result = event.apply(submission)

    assert result.creator.name == "Bob Proxied"
    assert result.creator.email == "bob@proxied.org"


def test_apply_sets_proxy_string():
    submitter = _make_submitter()
    submission = _make_submission(submitter)

    event = SetProxyInformation(
        creator=submitter,
        proxied_name="Bob Proxied",
        proxied_email="bob@proxied.org",
        proxy_name="David Submitter",
    )

    result = event.apply(submission)

    # proxy is now a plain string identifying the proxy submitter, not a User.
    assert isinstance(result.proxy, str)
    assert result.proxy == "David Submitter"


def test_apply_preserves_creator_user_id():
    """Proxying must not change which user account owns the submission.

    Only the displayed contact name/email change. ``user_id`` is the legacy
    ``submitter_id`` and must stay tied to the proxy submitter's account.
    """
    submitter = _make_submitter()
    submission = _make_submission(submitter)

    event = SetProxyInformation(
        creator=submitter,
        proxied_name="Bob Proxied",
        proxied_email="bob@proxied.org",
        proxy_name="David Submitter",
    )

    result = event.apply(submission)

    assert result.creator.user_id == "123"
    assert result.owner.user_id == "123"


def test_apply_leaves_the_given_submission_unchanged():
    """Like every event, ``apply`` returns the updated copy."""
    submitter = _make_submitter()
    submission = _make_submission(submitter)

    event = SetProxyInformation(
        creator=submitter,
        proxied_name="Bob Proxied",
        proxied_email="bob@proxied.org",
        proxy_name="David Submitter",
    )

    result = event.apply(submission)

    assert result.creator.name == "Bob Proxied"
    assert submission.creator.name == "David Submitter"


def test_apply_overwrites_existing_proxy_information():
    """Applying the event a second time replaces previous proxy values."""
    submitter = _make_submitter()
    submission = _make_submission(submitter)

    first = SetProxyInformation(
        creator=submitter,
        proxied_name="Bob Proxied",
        proxied_email="bob@proxied.org",
        proxy_name="David Submitter",
    )
    first.apply(submission)

    second = SetProxyInformation(
        creator=submitter,
        proxied_name="Carol Contact",
        proxied_email="carol@contact.org",
        proxy_name="David Submitter",
    )
    result = second.apply(submission)

    assert result.creator.name == "Carol Contact"
    assert result.creator.email == "carol@contact.org"
    assert result.proxy == "David Submitter"


def test_apply_does_not_modify_unrelated_submission_fields():
    """Only creator name/email and proxy should change."""
    submitter = _make_submitter()
    submission = _make_submission(submitter)
    submission.submitter_is_author = True
    submission.submitter_accepts_policy = True
    submission.version = 2
    submission.arxiv_id = "2401.00001"

    event = SetProxyInformation(
        creator=submitter,
        proxied_name="Bob Proxied",
        proxied_email="bob@proxied.org",
        proxy_name="David Submitter",
    )

    result = event.apply(submission)

    assert result.submitter_is_author is True
    assert result.submitter_accepts_policy is True
    assert result.version == 2
    assert result.arxiv_id == "2401.00001"
    assert result.owner.user_id == submitter.user_id
