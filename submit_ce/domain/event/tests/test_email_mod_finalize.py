"""Unit tests for `EmailModeratorsFinalizeMsg` (the on-finalize moderator email).

The event's `execute` side effect is exercised directly with hand-built
submissions and a stub API, so no app, DB, or file store is needed. Sending must
be non-fatal: a failure is recorded on `event.error`, never raised. The To /
Reply-To sets are derived from the per-moderator opt-out flags; To falls back to
the archival admin when no moderator is eligible.
"""
from datetime import datetime

from pytz import UTC

from submit_ce.domain import agent
from submit_ce.domain.meta import Classification
from submit_ce.domain.config import SubmitConfig
from submit_ce.domain.moderator import Moderator
from submit_ce.domain.proposal import Proposal, ProposalStatus
from submit_ce.domain.event import EmailModeratorsFinalizeMsg
from submit_ce.domain.submission import (
    Submission, SubmissionMetadata, SubmissionType,
)
from submit_ce.implementations.email.email_in_memory import EmailInMemory


def _submitter():
    return agent.PublicUser(name="Sam Submitter", user_id="u1",
                            email="submitter@example.org", endorsements=[])


def _submission(submission_type=SubmissionType.NEW, arxiv_id=None,
                proposals=None, secondaries=None):
    u = _submitter()
    return Submission(
        submission_id="12345",
        creator=u, owner=u, created=datetime.now(UTC),
        primary_classification=Classification(category="astro-ph.GA"),
        secondary_classification=list(secondaries or []),
        submission_type=submission_type,
        arxiv_id=arxiv_id,
        proposals=proposals or {},
        metadata=SubmissionMetadata(title="A Fine Paper",
                                    authors_display="Sam Submitter",
                                    abstract="An abstract."))


def _mods():
    # Distinct opt-out flags so To and Reply-To diverge.
    return [
        Moderator(user_id="2", email="ag@example.org", archive="astro-ph",
                  subject_class="GA", name="Alice Gauss"),
        Moderator(user_id="3", email="bee@example.org", archive="astro-ph",
                  subject_class="", name="Bee Admin", no_email=True),
        Moderator(user_id="4", email="cee@example.org", archive="astro-ph",
                  subject_class="GA", name="Cee Reply", no_reply_to=True),
    ]


def _event(**kwargs):
    defaults = dict(
        creator=agent.System(name="test"),
        submission_id="12345",
        created=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return EmailModeratorsFinalizeMsg(**defaults)


class _Api:
    """Stub exposing get_email_service, get_config, moderators_for_categories."""
    def __init__(self, service, mods=None, config=None):
        self._service = service
        self._mods = mods if mods is not None else _mods()
        self._config = config or SubmitConfig(
            mod_reply_to_email="mod-admin-email@arxiv.example.org",
            archival_email="local-admin-email@arxiv.example.org")
        self.last_call = None

    def get_email_service(self):
        return self._service

    def get_config(self):
        return self._config

    def moderators_for_categories(self, categories, **kwargs):
        self.last_call = (list(categories), kwargs)
        return list(self._mods)


# --- execute(): header composition ---

def test_to_excludes_no_email_reply_to_excludes_no_reply_to():
    service = EmailInMemory()
    api = _Api(service)
    _event().execute(api, _submission())

    sent = service.last
    # To: drops the no_email moderator (bee).
    assert sent.to == ["ag@example.org", "cee@example.org"]
    # Reply-To: mod-admin first, then moderators minus the no_reply_to one (cee).
    assert sent.reply_to == \
        "mod-admin-email@arxiv.example.org,ag@example.org,bee@example.org"
    assert sent.bcc == ["local-admin-email@arxiv.example.org"]


def test_fetches_full_candidate_set_without_web_email_exclusion():
    api = _Api(EmailInMemory())
    _event().execute(api, _submission())
    cats, kwargs = api.last_call
    assert kwargs.get("exclude_no_web_email") is False


def test_no_moderators_falls_back_to_local_admin():
    service = EmailInMemory()
    _event().execute(_Api(service, mods=[]), _submission())
    sent = service.last
    assert sent.to == ["local-admin-email@arxiv.example.org"]
    assert sent.reply_to == "mod-admin-email@arxiv.example.org"
    assert sent.bcc == []  # Bcc omitted on the fallback


def test_all_no_email_moderators_falls_back():
    mods = [Moderator(user_id="9", email="x@example.org", archive="astro-ph",
                      subject_class="GA", no_email=True)]
    service = EmailInMemory()
    _event().execute(_Api(service, mods=mods), _submission())
    sent = service.last
    assert sent.to == ["local-admin-email@arxiv.example.org"]
    # The no_email moderator is still eligible for Reply-To.
    assert sent.reply_to == "mod-admin-email@arxiv.example.org,x@example.org"


def test_submitter_is_never_a_recipient():
    service = EmailInMemory()
    _event().execute(_Api(service), _submission())
    sent = service.last
    recipients = sent.to + sent.bcc + [sent.reply_to]
    assert all("submitter@example.org" not in r for r in recipients)


def test_threading_message_id_is_stable():
    service = EmailInMemory()
    _event().execute(_Api(service), _submission())
    sent = service.last
    assert sent.message_id == "<submit.12345@arxiv.org>"
    assert sent.references == sent.message_id


# --- execute(): per-type subjects/bodies ---

def test_new_subject_and_review_link():
    service = EmailInMemory()
    _event().execute(_Api(service), _submission())
    sent = service.last
    assert sent.subject == \
        "arXiv submission 12345 to astro-ph.GA by Sam Submitter"
    assert "View the submission: https://check.arxiv.org/submit/12345" in sent.body


def test_new_lists_system_proposed_primaries():
    proposals = {"p1": Proposal(proposal_id="p1", category="math.AG",
                                is_primary=True, creator=agent.System(name="cls"),
                                status=ProposalStatus.UNRESOLVED)}
    service = EmailInMemory()
    _event().execute(_Api(service), _submission(proposals=proposals))
    assert "System-proposed primaries: math.AG" in service.last.body


def test_replacement_subject():
    service = EmailInMemory()
    _event().execute(_Api(service),
                     _submission(SubmissionType.REPLACEMENT, arxiv_id="2401.00001"))
    assert service.last.subject == \
        "arXiv replacement 12345 for 2401.00001 by Sam Submitter"


def test_withdrawal_subject():
    service = EmailInMemory()
    _event().execute(_Api(service),
                     _submission(SubmissionType.WITHDRAWAL, arxiv_id="2401.00001"))
    sent = service.last
    assert sent.subject == "arXiv withdrawal 12345 for 2401.00001 by Sam Submitter"
    assert "View the withdrawal:" in sent.body


def test_cross_subject_and_body():
    """The subject names only the categories the cross is adding.

    A cross-list carries the paper's announced categories too (published), and
    those must not appear as though they were being requested.
    """
    service = EmailInMemory()
    submission = _submission(
        SubmissionType.CROSS_LIST, arxiv_id="2401.00001",
        secondaries=[Classification(category="astro-ph.CO", is_published=True),
                     Classification(category="cs.DL")])
    _event().execute(_Api(service), submission)
    sent = service.last
    assert sent.subject == \
        "arXiv cross 12345 to cs.DL for 2401.00001 by Sam Submitter"
    assert "A crosslist has been added by submitter Sam Submitter" in sent.body


# --- execute(): recipient resolution ---

def test_categories_to_email_includes_unresolved_proposals():
    proposals = {
        "p1": Proposal(proposal_id="p1", category="math.AG", is_primary=False,
                       creator=agent.System(name="cls"),
                       status=ProposalStatus.UNRESOLVED),
        "p2": Proposal(proposal_id="p2", category="cs.AI", is_primary=True,
                       creator=agent.System(name="cls"),
                       status=ProposalStatus.REJECTED),
    }
    sub = _submission(proposals=proposals)
    # Primary astro-ph.GA + unresolved math.AG; rejected cs.AI excluded.
    assert _event().categories_to_email(sub) == ["astro-ph.GA", "math.AG"]


# --- execute(): non-fatal failure modes ---

def test_send_failure_is_recorded_not_raised():
    class _Raising(EmailInMemory):
        def send_email(self, *a, **k):
            raise RuntimeError("smtp boom")

    event = _event()
    event.execute(_Api(_Raising()), _submission())  # must not raise
    assert event.error is not None
    assert "smtp boom" in event.error


def test_no_service_records_error():
    event = _event()
    event.execute(_Api(None), _submission())
    assert event.error is not None
    assert "not configured" in event.error


def test_project_is_noop():
    sub = _submission()
    assert _event().project(sub) is sub
