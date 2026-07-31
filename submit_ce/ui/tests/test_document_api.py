"""Tests for the Document side of the api.

``get_document`` / ``load_documents_for_user`` / ``has_active_submission``.
"""
from datetime import datetime, UTC

import pytest
from arxiv.db import models as classic
from arxiv.db import Session
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.document import Document
from submit_ce.domain.event import CreateSubmission, CreateSubmissionVersion
from submit_ce.domain.exceptions import NoSuchDocument
from submit_ce.implementations.legacy_implementation.models import \
    Submission as LegacyRow


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
        journal_ref='foo journal 1992', doi='10.1000/182',
        report_num='CERN-PH-EP/2999-018', source_size=59392,
        is_current=1, is_withdrawn=0)
    fields.update(overrides)
    with Session() as session:
        session.add(classic.Metadata(**fields))
        session.commit()


def _add_document_categories(document_id, primary, secondaries):
    with Session() as session:
        session.add(classic.DocumentCategory(
            document_id=document_id, category=primary, is_primary=1))
        for cat in secondaries:
            session.add(classic.DocumentCategory(
                document_id=document_id, category=cat, is_primary=0))
        session.commit()


def _announce(submission_id):
    """Announce a finalized submission, as the `published_submission` fixture does.

    Lets a test have a *second* announced paper for the same user, which the
    fixture cannot give (it is function scoped and mints one paper). The paper id
    is minted the same way the fixture mints it -- one past the highest -- so
    that a later use of the fixture in the same session does not collide with it.
    """
    with Session() as session:
        highest = session.query(classic.Document.paper_id) \
                         .order_by(classic.Document.paper_id.desc()) \
                         .limit(1).scalar()
        yymm, number = highest.split('.')
        paper_id = f'{yymm}.{int(number) + 1}'

        row = session.get(classic.Submission, int(submission_id))
        row.status = LegacyRow.ANNOUNCED
        row.paper_id = paper_id
        row.doc_paper_id = paper_id
        document = classic.Document(paper_id=paper_id, title=row.title,
                                    submitter_email=row.submitter_email,
                                    submitter_id=row.submitter_id,
                                    created=datetime.now(UTC))
        row.document = document
        session.add(row)
        session.add(document)
        session.commit()
        return paper_id


def _by_paper_id(documents, paper_id):
    """The one document for `paper_id`.

    Tests share a database, so a user accumulates announced papers from earlier
    tests' fixtures; a test asserts about its own paper rather than the list.
    """
    matching = [d for d in documents if d.paper_id == paper_id]
    assert len(matching) == 1, f'{paper_id} not returned exactly once'
    return matching[0]


def test_get_document(app, published_submission):
    submission, paper_id = published_submission
    with app.app_context():
        document_id = _document_id_for(paper_id)
        _add_metadata(paper_id, document_id)
        _add_document_categories(document_id, 'astro-ph.GA', ['astro-ph.CO'])

        doc = current_app.api.get_document(paper_id)

        assert isinstance(doc, Document)
        assert doc.paper_id == paper_id
        assert doc.document_id == document_id
        assert doc.latest_version == 1

        # Per-version metadata comes from arXiv_metadata.
        assert len(doc.metadata) == 1
        md = doc.metadata[0]
        assert md.version == 1
        assert md.title == 'Foo bar and the right data'
        assert md.doi == '10.1000/182'
        assert md.journal_ref == 'foo journal 1992'
        assert md.categories == 'astro-ph.GA astro-ph.CO'
        assert md.is_current is True
        assert doc.current_metadata is md

        # Current categories come from arXiv_document_category.
        assert doc.primary_classification.category == 'astro-ph.GA'
        assert [c.category for c in doc.secondary_classification] == ['astro-ph.CO']

        # All submissions on the paper are present; none are active yet.
        assert len(doc.submissions) == 1
        assert doc.submissions[0].arxiv_id == paper_id
        assert doc.has_active_submission is False
        assert doc.active_submissions == []


def test_get_document_not_found(app, published_submission):
    with app.app_context():
        with pytest.raises(NoSuchDocument):
            current_app.api.get_document('9999.99999')


def test_load_documents_for_user(app, authorized_user, published_submission):
    """The user's announced papers, assembled the same way `get_document` does."""
    submission, paper_id = published_submission
    with app.app_context():
        document_id = _document_id_for(paper_id)
        _add_metadata(paper_id, document_id)
        _add_document_categories(document_id, 'astro-ph.GA', ['astro-ph.CO'])

        docs = current_app.api.load_documents_for_user(
            authorized_user.user_id)

        doc = _by_paper_id(docs, paper_id)
        assert isinstance(doc, Document)
        assert doc.document_id == document_id
        assert doc.submitter_id == int(authorized_user.user_id)
        # Bulk assembly must not skip metadata or categories.
        assert doc.current_metadata.title == 'Foo bar and the right data'
        assert doc.primary_classification.category == 'astro-ph.GA'
        assert [c.category for c in doc.secondary_classification] \
            == ['astro-ph.CO']
        assert [str(s.submission_id) for s in doc.submissions] \
            == [str(submission.submission_id)]


def test_load_documents_for_user_without_metadata_rows(
        app, authorized_user, published_submission):
    """A paper announced here has no `arXiv_metadata` row until legacy writes one.

    `to_document` tolerates that (`Document._metadata_from_announced` covers
    it), so the bulk query must too rather than assuming a row per paper.
    """
    _, paper_id = published_submission
    with app.app_context():
        doc = _by_paper_id(
            current_app.api.load_documents_for_user(authorized_user.user_id),
            paper_id)

        assert doc.metadata == []
        assert doc.primary_classification is None
        # The announced submission still stands in for the paper's state.
        assert doc.seed_submission(authorized_user).metadata.title \
            == 'Foo bar and the right data'


def test_load_documents_for_user_excludes_unannounced(
        app, authorized_user, published_submission):
    """Only announced papers; an in-progress submission is not a document.

    `load_submissions_for_user` is the other half of the pair and covers those.
    """
    with app.app_context():
        before = current_app.api.load_documents_for_user(
            authorized_user.user_id)

        working, _ = current_app.api.save(CreateSubmission(
            creator=authorized_user,
            client=InternalClient(name='test_document_api')))

        after = current_app.api.load_documents_for_user(
            authorized_user.user_id)
        assert [d.paper_id for d in after] == [d.paper_id for d in before]
        assert not any(str(working.submission_id) in
                       [str(s.submission_id) for s in d.submissions]
                       for d in after)


def test_load_documents_for_user_is_per_user(app, authorized_user,
                                             published_submission):
    """Another user's announced paper is not theirs to act on."""
    with app.app_context():
        assert current_app.api.load_documents_for_user('999999') == []


def test_load_documents_for_user_newest_first(app, authorized_user,
                                             published_submission,
                                             submitted_submission):
    """Several papers come back most recently submitted first."""
    _, first_paper_id = published_submission
    with app.app_context():
        second_paper_id = _announce(submitted_submission.submission_id)

        paper_ids = [d.paper_id for d in
                     current_app.api.load_documents_for_user(
                         authorized_user.user_id)]

        assert paper_ids.index(second_paper_id) \
            < paper_ids.index(first_paper_id)


def test_load_documents_for_user_carries_active_submissions(
        app, authorized_user, published_submission):
    """The active submissions on each paper come along.

    This is what the dashboard needs to decide whether to offer Replace /
    Withdraw / Add Journal Reference for a paper, or to show the request that
    is already in progress.
    """
    submission, paper_id = published_submission
    with app.app_context():
        current_app.api.save(
            CreateSubmissionVersion(
                creator=authorized_user,
                client=InternalClient(name='test_document_api')),
            submission_id=submission.submission_id)

        doc = _by_paper_id(
            current_app.api.load_documents_for_user(authorized_user.user_id),
            paper_id)

        assert doc.has_active_submission is True
        assert {s.submission_type.value
                for s in doc.active_submissions} == {'rep'}


def test_has_active_submission(app, authorized_user, published_submission):
    submission, paper_id = published_submission
    submission_id = submission.submission_id

    with app.app_context():
        # Only the announced row exists.
        assert current_app.api.has_active_submission(paper_id) is False

        # Start a replacement (in-progress, not announced).
        ua = InternalClient(name="test_rep")
        current_app.api.save(
            CreateSubmissionVersion(creator=authorized_user, client=ua),
            submission_id=submission_id)

        assert current_app.api.has_active_submission(paper_id) is True

        # The active rep should surface on the Document too.
        doc = current_app.api.get_document(paper_id)
        assert doc.has_active_submission is True
        assert {s.submission_type.value for s in doc.active_submissions} == {'rep'}
