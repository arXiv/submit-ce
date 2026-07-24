"""Tests for SubmitApi.get_document / has_active_submission (Document domain)."""
import pytest
from arxiv.db import models as classic
from arxiv.db import Session
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.document import Document
from submit_ce.domain.event import CreateSubmissionVersion
from submit_ce.domain.exceptions import NoSuchDocument


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
