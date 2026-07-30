"""Tests for `CreateJrefSubmission` against the classic database.

These exercise the real `api.save` path -- the jref row creation in
`db.store_jref_create` and the `store_event` routing that keeps later events on
the jref's own row.
"""
import pytest
from arxiv.db import Session
from arxiv.db import models as classic
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import CreateJrefSubmission, CreateSubmissionVersion, \
    SetDOI, SetJournalReference
from submit_ce.domain.exceptions import InvalidEvent, NoSuchDocument, SaveError
from submit_ce.domain.submission import Submission, SubmissionType
from submit_ce.implementations.legacy_implementation.models import \
    Submission as LegacyRow

JOURNAL_REF = 'Phys. Rev. D 100, 1 (2019)'


def _rows_for(paper_id):
    with Session() as session:
        return session.query(classic.Submission) \
                      .filter(classic.Submission.doc_paper_id == paper_id) \
                      .order_by(classic.Submission.submission_id.asc()).all()


def _row(submission_id):
    with Session() as session:
        return session.query(classic.Submission) \
                      .filter(classic.Submission.submission_id
                              == int(submission_id)).one()


def _document_id_for(paper_id):
    with Session() as session:
        row = session.query(classic.Submission) \
                     .filter(classic.Submission.doc_paper_id == paper_id) \
                     .filter(classic.Submission.type == 'new').one()
        return row.document_id


def _add_metadata(paper_id, document_id, **overrides):
    fields = dict(
        document_id=document_id, paper_id=paper_id, version=1,
        submitter_name='Bob Paulson', submitter_email='foo@foo.com',
        title='Foo bar and the right data', authors='Bob Paulson (Fight Club)',
        abstract='the abstract', abs_categories='astro-ph.GA astro-ph.CO',
        source_size=59392, is_current=1, is_withdrawn=0)
    fields.update(overrides)
    with Session() as session:
        session.add(classic.Metadata(**fields))
        session.commit()


def _add_document_categories(document_id, primary, secondaries=()):
    with Session() as session:
        session.add(classic.DocumentCategory(
            document_id=document_id, category=primary, is_primary=1))
        for cat in secondaries:
            session.add(classic.DocumentCategory(
                document_id=document_id, category=cat, is_primary=0))
        session.commit()


@pytest.fixture
def announced_paper(app, published_submission):
    """A published paper with the arXiv_metadata/category rows a jref needs."""
    submission, paper_id = published_submission
    with app.app_context():
        document_id = _document_id_for(paper_id)
        _add_metadata(paper_id, document_id)
        _add_document_categories(document_id, 'astro-ph.GA', ['astro-ph.CO'])
    return submission, paper_id, document_id


def test_creates_its_own_jref_row(app, authorized_user, announced_paper):
    """A jref gets a new row of its own, leaving the announced row alone."""
    announced, paper_id, document_id = announced_paper
    ua = InternalClient(name='test_jref')

    with app.app_context():
        before_rows = _rows_for(paper_id)

        after, events = current_app.api.save(CreateJrefSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id,
            journal_ref=JOURNAL_REF, doi='10.1000/182'))

        # A brand new submission, not the announced one.
        assert after.submission_id is not None
        assert after.submission_id != announced.submission_id
        assert after.submission_type is SubmissionType.JOURNAL_REFERENCE
        assert after.arxiv_id == paper_id

        rows = _rows_for(paper_id)
        assert len(rows) == len(before_rows) + 1

        row = _row(after.submission_id)
        assert row.type == 'jref'
        # Created but not yet submitted, as in legacy.
        assert row.status == LegacyRow.WORKING
        assert row.document_id == document_id
        assert row.doc_paper_id == paper_id
        assert row.journal_ref == JOURNAL_REF
        assert row.doi == '10.1000/182'
        # Metadata is seeded from the announced version.
        assert row.title == 'Foo bar and the right data'
        assert row.package == str(row.submission_id)

        # The announced row is untouched.
        announced_row = _row(announced.submission_id)
        assert announced_row.status == LegacyRow.ANNOUNCED
        assert announced_row.journal_ref in (None, '')


def test_version_is_not_incremented(app, authorized_user, announced_paper):
    """A jref annotates the current version rather than making a new one."""
    announced, paper_id, _ = announced_paper
    ua = InternalClient(name='test_jref')

    with app.app_context():
        after, _ = current_app.api.save(CreateJrefSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id,
            doi='10.1000/182'))

        assert after.version == announced.version
        assert _row(after.submission_id).version == announced.version


def test_replays_as_a_jref(app, authorized_user, announced_paper):
    """The new submission loads back from its own id as a jref."""
    _, paper_id, _ = announced_paper
    ua = InternalClient(name='test_jref')

    with app.app_context():
        after, _ = current_app.api.save(CreateJrefSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id,
            journal_ref=JOURNAL_REF))

        loaded = current_app.api.get(after.submission_id)

        assert loaded.submission_type is SubmissionType.JOURNAL_REFERENCE
        assert loaded.arxiv_id == paper_id
        assert loaded.metadata.journal_ref == JOURNAL_REF
        assert loaded.status == Submission.WORKING


def test_later_events_land_on_the_jref_row(app, authorized_user,
                                           announced_paper):
    """Editing the jref updates the jref row, not the announced one.

    `_load` by paper_id defaults to the new/rep rows, so without explicit
    routing on the submission type this would write to the announced row.
    """
    announced, paper_id, _ = announced_paper
    ua = InternalClient(name='test_jref')

    with app.app_context():
        jref, _ = current_app.api.save(CreateJrefSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id,
            journal_ref='first ref 1999'))

        current_app.api.save(
            SetJournalReference(creator=authorized_user, client=ua,
                                journal_ref=JOURNAL_REF),
            submission_id=jref.submission_id)

        assert _row(jref.submission_id).journal_ref == JOURNAL_REF
        # The announced row did not absorb the edit.
        assert _row(announced.submission_id).journal_ref in (None, '')
        # And no extra row was created.
        assert len([r for r in _rows_for(paper_id) if r.type == 'jref']) == 1


def test_copies_the_papers_categories(app, authorized_user, announced_paper):
    """The jref row inherits the paper's current primary and secondaries.

    These come from arXiv_document_category via the seeded Document, not from
    the announced submission row's own categories.
    """
    _, paper_id, _ = announced_paper
    ua = InternalClient(name='test_jref')

    with app.app_context():
        after, _ = current_app.api.save(CreateJrefSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id,
            doi='10.1000/182'))

        assert after.primary_classification.category == 'astro-ph.GA'
        assert [c.category for c in after.secondary_classification] \
            == ['astro-ph.CO']

        with Session() as session:
            cats = session.query(classic.SubmissionCategory) \
                          .filter(classic.SubmissionCategory.submission_id
                                  == int(after.submission_id)).all()
        assert {(c.category, bool(c.is_primary)) for c in cats} == {
            ('astro-ph.GA', True), ('astro-ph.CO', False)}


def test_event_survives_a_serialization_round_trip(app, authorized_user,
                                                   announced_paper):
    """The stored event deserializes with its fields intact.

    `paper_id` is required on the event, so if it were not persisted in the
    event payload `DBEvent.to_event()` would fail to reconstruct it.
    """
    _, paper_id, _ = announced_paper
    ua = InternalClient(name='test_jref')

    with app.app_context():
        after, _ = current_app.api.save(CreateJrefSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id,
            journal_ref=JOURNAL_REF, doi='10.1000/182',
            report_num='CERN-PH-EP/2999-018'))

        _, events = current_app.api.get_with_history(after.submission_id)

        created = [e for e in events if isinstance(e, CreateJrefSubmission)]
        assert len(created) == 1
        assert created[0].paper_id == paper_id
        assert created[0].journal_ref == JOURNAL_REF
        assert created[0].doi == '10.1000/182'
        assert created[0].report_num == 'CERN-PH-EP/2999-018'
        assert created[0].creator.user_id == authorized_user.user_id


def test_unknown_paper_is_rejected(app, authorized_user, announced_paper):
    """There is no document to seed from, so the save fails."""
    ua = InternalClient(name='test_jref')

    with app.app_context():
        with pytest.raises(NoSuchDocument):
            current_app.api.save(CreateJrefSubmission(
                creator=authorized_user, client=ua, paper_id='9999.99999',
                doi='10.1000/182'))


def test_cannot_be_combined_with_other_events(app, authorized_user,
                                              announced_paper):
    """This event creates its own submission, so it must be saved alone."""
    _, paper_id, _ = announced_paper
    ua = InternalClient(name='test_jref')

    with app.app_context():
        with pytest.raises(SaveError, match='only item'):
            current_app.api.save(
                CreateJrefSubmission(creator=authorized_user, client=ua,
                                     paper_id=paper_id, doi='10.1000/182'),
                SetDOI(creator=authorized_user, client=ua, doi='10.1000/183'))

        assert [r for r in _rows_for(paper_id) if r.type == 'jref'] == []


def test_a_second_jref_is_rejected(app, authorized_user, announced_paper):
    """A paper gets one in-progress journal reference at a time.

    A second one would be a competing edit of the same fields, so it is
    rejected and no second row is created; the caller should send the user to
    the existing jref instead.
    """
    _, paper_id, _ = announced_paper
    ua = InternalClient(name='test_jref')

    with app.app_context():
        first, _ = current_app.api.save(CreateJrefSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id,
            journal_ref='first ref 1999'))

        with pytest.raises(InvalidEvent, match='already has a submission'):
            current_app.api.save(CreateJrefSubmission(
                creator=authorized_user, client=ua, paper_id=paper_id,
                doi='10.1000/182'))

        jrefs = [r for r in _rows_for(paper_id) if r.type == 'jref']
        assert len(jrefs) == 1
        assert jrefs[0].submission_id == int(first.submission_id)
        # The first jref is untouched by the rejected attempt.
        assert jrefs[0].journal_ref == 'first ref 1999'
        assert jrefs[0].doi in (None, '')


def test_rejects_when_a_replacement_is_in_progress(app, authorized_user,
                                                   announced_paper):
    """A non-jref active submission blocks a new journal reference."""
    announced, paper_id, _ = announced_paper
    ua = InternalClient(name='test_jref')

    with app.app_context():
        current_app.api.save(
            CreateSubmissionVersion(creator=authorized_user, client=ua),
            submission_id=announced.submission_id)

        with pytest.raises(InvalidEvent, match='already has a submission'):
            current_app.api.save(CreateJrefSubmission(
                creator=authorized_user, client=ua, paper_id=paper_id,
                doi='10.1000/182'))

        assert [r for r in _rows_for(paper_id) if r.type == 'jref'] == []
