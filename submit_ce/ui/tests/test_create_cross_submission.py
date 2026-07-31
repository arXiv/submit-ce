"""Tests for cross-list submissions against the classic database.

These exercise the real `api.save` path -- the cross row creation in
`db.store_cross_create`, the `store_event` routing that keeps later events on
the cross's own row, and the `arXiv_submission_category.is_published` split
between the paper's announced categories and the ones the cross is adding.
"""
import pytest
from arxiv.db import Session
from arxiv.db import models as classic
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import AddCrossCategory, CreateCrossSubmission, \
    CreateSubmissionVersion, FinalizeCrossSubmission, RemoveCrossCategory, \
    SetDOI
from submit_ce.domain.exceptions import InvalidEvent, NoSuchDocument, SaveError
from submit_ce.domain.submission import Submission, SubmissionType
from submit_ce.implementations.legacy_implementation.models import \
    Submission as LegacyRow


def _rows_for(paper_id, row_type=None):
    with Session() as session:
        query = session.query(classic.Submission) \
                       .filter(classic.Submission.doc_paper_id == paper_id)
        if row_type is not None:
            query = query.filter(classic.Submission.type == row_type)
        return query.order_by(classic.Submission.submission_id.asc()).all()


def _row(submission_id):
    with Session() as session:
        return session.query(classic.Submission) \
                      .filter(classic.Submission.submission_id
                              == int(submission_id)).one()


def _categories(submission_id):
    """``{(category, is_primary, is_published)}`` for a submission's rows."""
    with Session() as session:
        rows = session.query(classic.SubmissionCategory) \
                      .filter(classic.SubmissionCategory.submission_id
                              == int(submission_id)).all()
        return {(c.category, bool(c.is_primary), bool(c.is_published))
                for c in rows}


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
    """A published paper with the metadata/category rows a cross needs."""
    submission, paper_id = published_submission
    with app.app_context():
        document_id = _document_id_for(paper_id)
        _add_metadata(paper_id, document_id)
        _add_document_categories(document_id, 'astro-ph.GA', ['astro-ph.CO'])
    return submission, paper_id, document_id


@pytest.fixture
def ua():
    return InternalClient(name='test_cross')


def test_creates_its_own_cross_row(app, authorized_user, announced_paper, ua):
    """A cross gets a new row of its own, leaving the announced row alone."""
    announced, paper_id, document_id = announced_paper

    with app.app_context():
        before_rows = _rows_for(paper_id)

        after, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))

        assert after.submission_id is not None
        assert after.submission_id != announced.submission_id
        assert after.submission_type is SubmissionType.CROSS_LIST
        assert after.arxiv_id == paper_id

        assert len(_rows_for(paper_id)) == len(before_rows) + 1

        row = _row(after.submission_id)
        assert row.type == 'cross'
        # Created but not yet submitted, as in legacy.
        assert row.status == LegacyRow.WORKING
        assert row.document_id == document_id
        assert row.doc_paper_id == paper_id
        # Metadata is seeded from the announced version.
        assert row.title == 'Foo bar and the right data'

        # The announced row is untouched.
        assert _row(announced.submission_id).status == LegacyRow.ANNOUNCED


def test_version_is_not_incremented(app, authorized_user, announced_paper, ua):
    """A cross adds to the current version rather than making a new one."""
    announced, paper_id, _ = announced_paper

    with app.app_context():
        after, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))

        assert after.version == announced.version
        assert _row(after.submission_id).version == announced.version


def test_the_papers_categories_are_snapshot_as_published(
        app, authorized_user, announced_paper, ua):
    """Every inherited category lands with ``is_published = 1``.

    Legacy's `make_sub_cats`. Without it there is no way to tell an announced
    category from one this cross is requesting.
    """
    _, paper_id, _ = announced_paper

    with app.app_context():
        after, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))

        assert _categories(after.submission_id) == {
            ('astro-ph.GA', True, True), ('astro-ph.CO', False, True)}
        assert after.new_cross_categories == []


def test_added_categories_are_unpublished(app, authorized_user,
                                          announced_paper, ua):
    """The cross's own categories are stored with ``is_published = 0``."""
    _, paper_id, _ = announced_paper

    with app.app_context():
        cross, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))
        after, _ = current_app.api.save(
            AddCrossCategory(creator=authorized_user, client=ua,
                             category='cs.DL'),
            submission_id=cross.submission_id)

        assert after.new_cross_categories == ['cs.DL']
        assert _categories(cross.submission_id) == {
            ('astro-ph.GA', True, True),
            ('astro-ph.CO', False, True),
            ('cs.DL', False, False)}


def test_removing_a_category_deletes_only_its_row(app, authorized_user,
                                                  announced_paper, ua):
    """Removing a pending cross leaves the announced categories in place."""
    _, paper_id, _ = announced_paper

    with app.app_context():
        cross, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))
        current_app.api.save(
            AddCrossCategory(creator=authorized_user, client=ua,
                             category='cs.DL'),
            AddCrossCategory(creator=authorized_user, client=ua,
                             category='hep-th'),
            submission_id=cross.submission_id)

        after, _ = current_app.api.save(
            RemoveCrossCategory(creator=authorized_user, client=ua,
                                category='cs.DL'),
            submission_id=cross.submission_id)

        assert after.new_cross_categories == ['hep-th']
        assert _categories(cross.submission_id) == {
            ('astro-ph.GA', True, True),
            ('astro-ph.CO', False, True),
            ('hep-th', False, False)}


def test_replays_as_a_cross(app, authorized_user, announced_paper, ua):
    """The new submission loads back from its own id as a cross."""
    _, paper_id, _ = announced_paper

    with app.app_context():
        cross, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))
        current_app.api.save(
            AddCrossCategory(creator=authorized_user, client=ua,
                             category='cs.DL'),
            submission_id=cross.submission_id)

        loaded = current_app.api.get(cross.submission_id)

        assert loaded.submission_type is SubmissionType.CROSS_LIST
        assert loaded.arxiv_id == paper_id
        assert loaded.status == Submission.WORKING
        assert loaded.new_cross_categories == ['cs.DL']
        assert sorted(loaded.secondary_categories) == ['astro-ph.CO', 'cs.DL']


def test_later_events_land_on_the_cross_row(app, authorized_user,
                                            announced_paper, ua):
    """Editing the cross updates the cross row, not the announced one.

    `_load` by paper_id defaults to the new/rep rows, so without explicit
    routing on the submission type this would write to the announced row.
    """
    announced, paper_id, _ = announced_paper

    with app.app_context():
        cross, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))
        current_app.api.save(
            AddCrossCategory(creator=authorized_user, client=ua,
                             category='cs.DL'),
            submission_id=cross.submission_id)

        assert ('cs.DL', False, False) in _categories(cross.submission_id)
        assert 'cs.DL' not in {c for c, _, _
                               in _categories(announced.submission_id)}
        assert len(_rows_for(paper_id, 'cross')) == 1


def test_finalize_submits_the_cross_row(app, authorized_user,
                                        announced_paper, ua):
    """Finalizing moves the cross row to classic ``SUBMITTED`` with a time."""
    _, paper_id, _ = announced_paper

    with app.app_context():
        cross, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))
        current_app.api.save(
            AddCrossCategory(creator=authorized_user, client=ua,
                             category='cs.DL'),
            submission_id=cross.submission_id)

        after, _ = current_app.api.save(
            FinalizeCrossSubmission(creator=authorized_user, client=ua),
            submission_id=cross.submission_id)

        assert after.status == Submission.SUBMITTED
        row = _row(cross.submission_id)
        assert row.status == LegacyRow.SUBMITTED
        assert row.submit_time is not None
        # The pending cross is still pending; only publish announces it.
        assert ('cs.DL', False, False) in _categories(cross.submission_id)


def test_finalize_notifies_the_submitter_and_the_moderators(
        app, authorized_user, announced_paper, ua):
    """Both on-submit emails are sent, unlike for a journal reference."""
    _, paper_id, _ = announced_paper

    with app.app_context():
        cross, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))
        current_app.api.save(
            AddCrossCategory(creator=authorized_user, client=ua,
                             category='cs.DL'),
            submission_id=cross.submission_id)

        service = current_app.api.get_email_service()
        before = len(service.sent)
        current_app.api.save(
            FinalizeCrossSubmission(creator=authorized_user, client=ua),
            submission_id=cross.submission_id)

        sent = service.sent[before:]
        assert len(sent) == 2
        subjects = [msg.subject for msg in sent]
        # The subjects name only the category being added.
        assert f'arXiv cross to cs.DL for {paper_id}' in subjects
        assert any(s.startswith('arXiv cross ') and ' to cs.DL for ' in s
                   for s in subjects)


def test_finalize_needs_a_category(app, authorized_user, announced_paper, ua):
    """A cross with nothing added cannot be submitted."""
    _, paper_id, _ = announced_paper

    with app.app_context():
        cross, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))

        with pytest.raises(InvalidEvent, match='add categories'):
            current_app.api.save(
                FinalizeCrossSubmission(creator=authorized_user, client=ua),
                submission_id=cross.submission_id)

        assert _row(cross.submission_id).status == LegacyRow.WORKING


def test_event_survives_a_serialization_round_trip(app, authorized_user,
                                                   announced_paper, ua):
    """The stored event deserializes with its fields intact.

    `paper_id` is required on the event, so if it were not persisted in the
    event payload `DBEvent.to_event()` would fail to reconstruct it.
    """
    _, paper_id, _ = announced_paper

    with app.app_context():
        cross, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))

        _, events = current_app.api.get_with_history(cross.submission_id)

        created = [e for e in events if isinstance(e, CreateCrossSubmission)]
        assert len(created) == 1
        assert created[0].paper_id == paper_id
        assert created[0].creator.user_id == authorized_user.user_id


def test_unknown_paper_is_rejected(app, authorized_user, announced_paper, ua):
    """There is no document to seed from, so the save fails."""
    with app.app_context():
        with pytest.raises(NoSuchDocument):
            current_app.api.save(CreateCrossSubmission(
                creator=authorized_user, client=ua, paper_id='9999.99999'))


def test_cannot_be_combined_with_other_events(app, authorized_user,
                                              announced_paper, ua):
    """This event creates its own submission, so it must be saved alone."""
    _, paper_id, _ = announced_paper

    with app.app_context():
        with pytest.raises(SaveError, match='only item'):
            current_app.api.save(
                CreateCrossSubmission(creator=authorized_user, client=ua,
                                      paper_id=paper_id),
                SetDOI(creator=authorized_user, client=ua, doi='10.1000/183'))

        assert _rows_for(paper_id, 'cross') == []


def test_a_second_cross_is_rejected(app, authorized_user, announced_paper, ua):
    """A paper gets one in-progress cross-list at a time."""
    _, paper_id, _ = announced_paper

    with app.app_context():
        first, _ = current_app.api.save(CreateCrossSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))

        with pytest.raises(InvalidEvent, match='already has a submission'):
            current_app.api.save(CreateCrossSubmission(
                creator=authorized_user, client=ua, paper_id=paper_id))

        crosses = _rows_for(paper_id, 'cross')
        assert len(crosses) == 1
        assert crosses[0].submission_id == int(first.submission_id)


def test_rejects_when_a_replacement_is_in_progress(app, authorized_user,
                                                   announced_paper, ua):
    """A non-cross active submission blocks a new cross-list."""
    announced, paper_id, _ = announced_paper

    with app.app_context():
        current_app.api.save(
            CreateSubmissionVersion(creator=authorized_user, client=ua),
            submission_id=announced.submission_id)

        with pytest.raises(InvalidEvent, match='already has a submission'):
            current_app.api.save(CreateCrossSubmission(
                creator=authorized_user, client=ua, paper_id=paper_id))

        assert _rows_for(paper_id, 'cross') == []
