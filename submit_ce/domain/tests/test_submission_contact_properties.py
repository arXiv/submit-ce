"""Tests for the ``contact_name`` / ``contact_email`` properties on
:class:`.Submission`.

These derived properties surface "who appears as the contact" for a
submission. They mirror ``creator.name`` and ``creator.email`` directly,
which means they automatically reflect the proxied values once
:class:`.SetProxyInformation` has been applied (since that event mutates
``creator`` in place).

The properties are documented as "should eventually replace creator" — these
tests pin the current contract so any future refactor that decouples them
from ``creator`` will surface intentionally.
"""
from submit_ce.domain import Submission
from submit_ce.domain.agent import PublicUser
from submit_ce.domain.event import SetProxyInformation


def _make_submitter() -> PublicUser:
    return PublicUser(
        user_id="123",
        name="David Submitter",
        email="david@example.org",
    )


def test_contact_name_mirrors_creator_name():
    submitter = _make_submitter()
    submission = Submission(creator=submitter, owner=submitter)

    assert submission.contact_name == "David Submitter"


def test_contact_email_mirrors_creator_email():
    submitter = _make_submitter()
    submission = Submission(creator=submitter, owner=submitter)

    assert submission.contact_email == "david@example.org"


def test_contact_properties_reflect_proxied_values_after_event():
    """After ``SetProxyInformation`` is applied, the properties surface the
    proxied contact, not the proxy submitter's own name/email.
    """
    submitter = _make_submitter()
    submission = Submission(creator=submitter, owner=submitter)

    event = SetProxyInformation(
        creator=submitter,
        proxied_name="Bob Proxied",
        proxied_email="bob@proxied.org",
        proxy_name="David Submitter",
    )
    event.apply(submission)

    assert submission.contact_name == "Bob Proxied"
    assert submission.contact_email == "bob@proxied.org"


def test_contact_properties_track_creator_mutations():
    """The properties read through to ``creator`` on every access — mutating
    ``creator`` after construction is reflected immediately.
    """
    submitter = _make_submitter()
    submission = Submission(creator=submitter, owner=submitter)

    submission.creator.name = "Renamed Submitter"
    submission.creator.email = "renamed@example.org"

    assert submission.contact_name == "Renamed Submitter"
    assert submission.contact_email == "renamed@example.org"
