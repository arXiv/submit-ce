"""Unit tests for `EmailProposalModeratorsMsg` and its emission.

The event's `execute` side effect is exercised directly with hand-built
submissions and a stub API, so no app, DB, or file store is needed. Sending must
be non-fatal: a failure is recorded on `event.error`, never raised.
"""
from datetime import datetime

from pytz import UTC

from submit_ce.domain import agent
from submit_ce.domain.meta import Classification
from submit_ce.domain.config import SubmitConfig
from submit_ce.domain.moderator import Moderator
from submit_ce.domain.event import (
    EmailProposalModeratorsMsg,
    ProposeClassification,
)
from submit_ce.domain.proposal import Proposal, ProposalStatus
from submit_ce.domain.submission import Submission, SubmissionMetadata
from submit_ce.implementations.email.email_in_memory import EmailInMemory


def _submitter():
    return agent.PublicUser(name="Sam Submitter", user_id="u1",
                            email="submitter@example.org", endorsements=[])


def _submission():
    u = _submitter()
    return Submission(
        submission_id="12345",
        creator=u, owner=u, created=datetime.now(UTC),
        primary_classification=Classification(category="astro-ph.GA"),
        metadata=SubmissionMetadata(title="A Fine Paper"))


def _mods():
    return [
        Moderator(user_id="2", email="ag@example.org", archive="math",
                  subject_class="AG", name="Alice Gauss"),
        Moderator(user_id="3", email="matharch@example.org", archive="math",
                  subject_class="", name="Marc Archive"),
    ]


def _event(**kwargs):
    defaults = dict(
        creator=agent.System(name="test"),
        submission_id="12345",
        created=datetime.now(UTC),
        categories=["math.AG"],
        proposed_category="math.AG",
        is_primary=False,
        comment="please reclassify",
        proposer_name="Mod Erator",
    )
    defaults.update(kwargs)
    return EmailProposalModeratorsMsg(**defaults)


class _Api:
    """Stub exposing get_email_service, get_config, moderators_for_categories."""
    def __init__(self, service, mods=None, config=None):
        self._service = service
        self._mods = mods if mods is not None else _mods()
        # Explicit addresses (the domain defaults are non-real placeholders).
        self._config = config or SubmitConfig(
            mod_reply_to_email="mod-admin-email@arxiv.example.org",
            archival_email="local-admin-email@arxiv.example.org")

    def get_email_service(self):
        return self._service

    def get_config(self):
        return self._config

    def moderators_for_categories(self, categories):
        return list(self._mods)


# --- execute() ---

def test_sends_to_moderators_with_expected_headers():
    service = EmailInMemory()
    event = _event()
    event.execute(_Api(service), _submission())

    assert event.error is None
    sent = service.last
    assert sent.to == ["ag@example.org", "matharch@example.org"]
    # Reply-To = mod-admin then the moderator addresses.
    assert sent.reply_to == \
        "mod-admin-email@arxiv.example.org,ag@example.org,matharch@example.org"
    assert sent.bcc == ["local-admin-email@arxiv.example.org"]


def test_submitter_is_never_a_recipient():
    service = EmailInMemory()
    event = _event()
    event.execute(_Api(service), _submission())
    sent = service.last
    recipients = sent.to + sent.bcc + [sent.reply_to]
    assert all("submitter@example.org" not in r for r in recipients)


def test_subject_and_body_content():
    service = EmailInMemory()
    event = _event()
    event.execute(_Api(service), _submission())
    sent = service.last
    assert sent.subject == \
        "Re: arXiv submission 12345 to astro-ph.GA by Sam Submitter"
    assert "Proposed: math.AG as secondary" in sent.body
    assert "please reclassify" in sent.body
    assert "Mod Erator" in sent.body


def test_no_moderators_falls_back_to_local_admin():
    service = EmailInMemory()
    event = _event()
    event.execute(_Api(service, mods=[]), _submission())
    sent = service.last
    assert sent.to == ["local-admin-email@arxiv.example.org"]
    assert sent.reply_to == "mod-admin-email@arxiv.example.org"
    assert sent.bcc == []


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


# --- ProposeClassification.consequences() emission ---

def _moderator_user():
    return agent.StaffUser(user_id="4242", email="mod@arxiv.org",
                           name="Mod Erator", username="moderator")


def test_moderator_proposal_emits_one_email_event():
    sub = _submission()
    e = ProposeClassification(creator=_moderator_user(),
                              created=datetime.now(UTC),
                              category="math.AG",
                              is_primary=False,
                              comment="x")
    after = e.apply(sub)
    consequences = e.get_consequences(after)
    assert len(consequences) == 1
    msg = consequences[0]
    assert isinstance(msg, EmailProposalModeratorsMsg)
    assert msg.proposed_category == "math.AG"
    assert msg.proposer_name == "Mod Erator"
    assert msg.categories_to_email(sub) == ["math.AG"]


def test_primary_proposal_includes_current_primary_category():
    sub = _submission()  # current primary astro-ph.GA
    e = ProposeClassification(creator=_moderator_user(),
                              created=datetime.now(UTC),
                              category="math.AG", is_primary=True)
    after = e.apply(sub)
    msg = e.get_consequences(after)[0]
    # Moderators of both the proposed and the current primary are notified.
    assert msg.categories_to_email(sub) == ["astro-ph.GA", "math.AG"]


def test_system_proposal_emits_no_email():
    sub = _submission()
    e = ProposeClassification(creator=agent.System(name="classifier"),
                              created=datetime.now(UTC),
                              category="math.AG", is_primary=True)
    after = e.apply(sub)
    assert e.get_consequences(after) == []


# --- Which moderators actually receive the email ---
#
# These exercise the full recipient resolution (execute -> categories_to_email
# -> moderators_for_categories -> To addresses) with a per-category moderator
# resolver, so we can assert on the concrete recipient addresses rather than
# just on the category list.

def _add_proposal(sub, category, is_primary,
                  status=ProposalStatus.UNRESOLVED):
    """Attach a proposal for ``category`` to ``sub`` and return ``sub``."""
    pid = f"p-{category}-{'pri' if is_primary else 'sec'}"
    sub.proposals[pid] = Proposal(
        proposal_id=pid, category=category, is_primary=is_primary,
        creator=_moderator_user(), created=datetime.now(UTC), status=status)
    return sub


class _PerCategoryApi(_Api):
    """Resolve one distinct moderator per category.

    ``moderators_for_categories`` returns the union of moderators for exactly
    the requested categories (unknown categories resolve to nothing), so the
    ``To`` list reflects which categories the event chose to notify.
    """

    CATEGORY_MODS = {
        "astro-ph.GA": Moderator(user_id="10", email="mod-astro@example.org",
                                 archive="astro-ph", subject_class="GA"),
        "math.AG": Moderator(user_id="11", email="mod-mathag@example.org",
                             archive="math", subject_class="AG"),
        "cs.LG": Moderator(user_id="12", email="mod-cslg@example.org",
                           archive="cs", subject_class="LG"),
        "math.CO": Moderator(user_id="13", email="mod-mathco@example.org",
                             archive="math", subject_class="CO"),
        "q-bio.NC": Moderator(user_id="14", email="mod-qbio@example.org",
                              archive="q-bio", subject_class="NC"),
    }

    def moderators_for_categories(self, categories):
        return [self.CATEGORY_MODS[c] for c in categories
                if c in self.CATEGORY_MODS]


def test_primary_proposal_emails_current_proposed_and_unresolved_primary_mods():
    service = EmailInMemory()
    sub = _submission()  # current primary astro-ph.GA
    _add_proposal(sub, "cs.LG", is_primary=True)   # unresolved primary
    _add_proposal(sub, "math.CO", is_primary=True)  # unresolved primary
    # A resolved primary proposal and an unresolved secondary must NOT pull in
    # their moderators for a primary proposal.
    _add_proposal(sub, "q-bio.NC", is_primary=True,
                  status=ProposalStatus.REJECTED)
    _add_proposal(sub, "math.AG", is_primary=False)

    event = _event(proposed_category="math.AG", is_primary=True)
    event.execute(_PerCategoryApi(service), sub)

    assert event.error is None
    assert set(service.last.to) == {
        "mod-astro@example.org",   # current primary
        "mod-mathag@example.org",  # proposed primary
        "mod-cslg@example.org",    # unresolved primary proposal
        "mod-mathco@example.org",  # unresolved primary proposal
    }
    # The rejected primary proposal's moderator is not notified.
    assert "mod-qbio@example.org" not in service.last.to


def test_secondary_proposal_emails_only_proposed_category_mod():
    service = EmailInMemory()
    sub = _submission()  # current primary astro-ph.GA
    _add_proposal(sub, "cs.LG", is_primary=True)  # unresolved primary proposal

    event = _event(proposed_category="math.AG", is_primary=False)
    event.execute(_PerCategoryApi(service), sub)

    assert event.error is None
    # Only the proposed secondary's moderator is notified.
    assert service.last.to == ["mod-mathag@example.org"]
    # Neither the current primary's moderator nor the unresolved primary
    # proposal's moderator receive the email.
    assert "mod-astro@example.org" not in service.last.to
    assert "mod-cslg@example.org" not in service.last.to
