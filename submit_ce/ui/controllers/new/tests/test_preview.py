"""Tests for the HTML submission preview. [SUBMISSION-127]"""

from http import HTTPStatus as status

import arxiv.db.models as classic
import pytest
from arxiv.db import Session
from flask import current_app, request
from werkzeug.datastructures import MultiDict

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.document import DocMetadata, Document
from submit_ce.domain.event import ConfirmPreview, SetSourceFormat
from submit_ce.domain.exceptions import NoSuchDocument
from submit_ce.domain.uploads import SourceFormat
from submit_ce.implementations.file_store.mock_file_store import MockFileStore
from submit_ce.ui.controllers.new import final

PNG = b'\x89PNG\r\n\x1a\n'
PAGE = (b'<html><head><title>T</title></head>'
        b'<body><img src="/image1.png"></body></html>')
CSP = "sandbox allow-same-origin; default-src 'self' data:; style-src 'self' 'unsafe-inline'"


@pytest.fixture
def html_source(app, sub_files_html):
    """An HTML submission whose source is index.html and image1.png."""
    store = MockFileStore()
    app.api.store = store
    sid = str(sub_files_html.submission_id)
    store._source[sid] = {'index.html': PAGE, 'image1.png': PNG}
    return sid, store


def test_html_preview_index_redirects_to_the_only_page(authorized_client, html_source):
    sid, _ = html_source
    resp = authorized_client.get(f'/{sid}/preview/html/')
    assert resp.status_code == status.FOUND
    assert resp.headers['Location'].endswith(f'/{sid}/preview/html/index.html')


def test_html_preview_index_lists_several_pages(authorized_client, html_source):
    sid, store = html_source
    store._source[sid]['talks/b.html'] = PAGE
    resp = authorized_client.get(f'/{sid}/preview/html/')
    assert resp.status_code == status.OK
    assert f'href="/{sid}/preview/html/index.html"'.encode() in resp.data
    assert f'href="/{sid}/preview/html/talks/b.html"'.encode() in resp.data


def test_html_preview_serves_preprocessed_page(authorized_client, html_source):
    sid, _ = html_source
    resp = authorized_client.get(f'/{sid}/preview/html/index.html')
    assert resp.status_code == status.OK
    assert resp.headers['Content-Type'] == 'text/html; charset=utf-8'
    assert resp.headers['Content-Security-Policy'] == CSP
    assert resp.headers['Cache-Control'] == 'no-store'
    assert f'<base href="http://localhost/{sid}/preview/html/" />'.encode() in resp.data
    assert f'arXiv:submit/{sid}</a>'.encode() in resp.data
    assert b'src="image1.png"' in resp.data


def test_html_preview_loads_nothing_from_other_sites(authorized_client, html_source):
    """An image or stylesheet from elsewhere would tell the submitter when a
    moderator opened the page. Inline styles are harmless and kept."""
    sid, _ = html_source
    csp = authorized_client.get(f'/{sid}/preview/html/index.html').headers['Content-Security-Policy']
    assert "default-src 'self' data:" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp


def test_html_preview_records_the_preview_as_viewed(app, authorized_client, html_source):
    """Opening a page is the HTML analogue of opening preview.pdf."""
    sid, _ = html_source
    authorized_client.get(f'/{sid}/preview/html/index.html')
    with app.app_context():
        submission, _ = current_app.api.get_with_history(sid)
    assert submission.submitter_confirmed_preview


def test_html_preview_serves_assets_unchanged(authorized_client, html_source):
    sid, _ = html_source
    resp = authorized_client.get(f'/{sid}/preview/html/image1.png')
    assert resp.status_code == status.OK
    assert resp.data == PNG
    assert resp.mimetype == 'image/png'
    assert resp.headers['Content-Security-Policy'] == CSP


def test_html_preview_missing_file_is_404(authorized_client, html_source):
    sid, _ = html_source
    resp = authorized_client.get(f'/{sid}/preview/html/missing.png')
    assert resp.status_code == status.NOT_FOUND


def test_html_preview_is_404_for_non_html_submission(app, authorized_client, sub_files_tex):
    app.api.store = MockFileStore()
    resp = authorized_client.get(f'/{sub_files_tex.submission_id}/preview/html/')
    assert resp.status_code == status.NOT_FOUND


def test_finalize_gates_html_on_viewing_not_on_a_pdf(
        app, authorized_user, authorized_user_session, html_source):
    """HTML has no <id>.pdf: its preview exists when it has a page, and is
    ready once the submitter has viewed it."""
    sid, _ = html_source
    session, _ = authorized_user_session
    with app.test_request_context('/'):
        request.auth = session
        data, _, _ = final.finalize('GET', MultiDict(), session, sid)
        assert data['preview_exists'] and not data['preview_ready']

        current_app.api.save(
            ConfirmPreview(creator=authorized_user,
                           client=InternalClient(name='test_html_preview')),
            submission_id=sid)
    with app.test_request_context('/'):  # a new request, so no cached submission
        request.auth = session
        data, _, _ = final.finalize('GET', MultiDict(), session, sid)
        assert data['preview_ready']


def test_confirm_page_links_html_preview(app, authorized_user, authorized_client, sub_metadata):
    sid = str(sub_metadata.submission_id)
    store = MockFileStore()
    app.api.store = store
    store._source[sid] = {'index.html': PAGE}
    with app.app_context():
        current_app.api.save(
            SetSourceFormat(creator=authorized_user, client=InternalClient(name='test_html_preview'),
                            source_format=SourceFormat.HTML.value),
            submission_id=sid)

    resp = authorized_client.get(f'/{sid}/final_preview')

    assert resp.status_code == status.OK
    assert f'href="/{sid}/preview/html/"'.encode() in resp.data
    assert b'Preview your HTML!' in resp.data
    assert f'href="/{sid}/preview.pdf"'.encode() not in resp.data


def _metadata(**fields):
    return DocMetadata(**{'version': 1, 'title': 'Gaussian Process Topic Models',
                          'authors': 'Amrudin Agovic, Arindam Banerjee',
                          'categories': 'cs.LG stat.ML', 'abstract': 'We introduce a model.',
                          'is_current': True, **fields})


@pytest.fixture
def documents(app, mocker):
    """Announced papers that LIST: and ABS: lines can refer to."""
    papers = {'1203.3462': Document(paper_id='1203.3462', metadata=[
        _metadata(version=1, title='First version', is_current=False), _metadata(version=2)])}

    def get_document(paper_id):
        if paper_id not in papers:
            raise NoSuchDocument(paper_id)
        return papers[paper_id]

    mocker.patch.object(app.api, 'get_document', side_effect=get_document)
    return papers


def _preview(client, html_source, page: bytes) -> bytes:
    """The preview of an HTML submission whose only page is ``page``."""
    sid, store = html_source
    store._source[sid]['index.html'] = page
    return client.get(f'/{sid}/preview/html/index.html').data


def test_html_preview_expands_list_lines(authorized_client, html_source, documents):
    """arxiv-base expands the lines; the preview lists each paper from its
    announced metadata, and links to arxiv.org."""
    data = _preview(authorized_client, html_source,
                    b'<body>\nLIST:arXiv:1203.3462\nABS:1203.3462v1\n'
                    b'REPORT-NO:SampleWS/2026/01\n</body>')
    assert b'<a href="https://arxiv.org/abs/1203.3462" title="Abstract">' in data
    assert b'Gaussian Process Topic Models' in data
    assert b'Amrudin Agovic, Arindam Banerjee' in data
    assert b'Machine Learning (cs.LG)' in data
    assert b'<a href="https://arxiv.org/abs/1203.3462v1" title="Abstract">' in data
    assert b'First version' in data
    assert data.count(b'We introduce a model.') == 1
    assert (b'<a href="https://arxiv.org/search/?searchtype=report_num'
            b'&query=SampleWS%2F2026%2F01">') in data


def test_html_preview_leaves_unknown_papers_as_browse_does(authorized_client, html_source,
                                                           documents):
    lines = b'\nLIST:arXiv:1203.9999\nLIST:arXiv:1203.3462v3\n'
    assert lines in _preview(authorized_client, html_source, b'<body>' + lines + b'</body>')


def test_html_preview_escapes_listing_metadata(authorized_client, html_source, documents):
    documents['1203.3462'].metadata[1].title = '<script>alert(1)</script>'
    data = _preview(authorized_client, html_source, b'<body>\nLIST:1203.3462\n</body>')
    assert b'<script>' not in data and b'&lt;script&gt;' in data


def test_html_preview_survives_a_paper_that_fails_to_load(app, authorized_client, html_source,
                                                          mocker, caplog):
    """A listing that cannot be built must not break the rest of the page."""
    mocker.patch.object(app.api, 'get_document', side_effect=ValueError('bad row'))
    lines = b'\n<p>x</p>\nLIST:arXiv:1203.3462\n'
    assert lines in _preview(authorized_client, html_source, b'<body>' + lines + b'</body>')
    assert 'bad row' in caplog.text


MODERATOR_ID = '900004'
"""A moderator seeded by make_test_db (cs.AI)."""


def test_is_moderator(app, authorized_user):
    with app.app_context():
        assert current_app.api.is_moderator(MODERATOR_ID)
        assert not current_app.api.is_moderator(str(authorized_user.user_id))


def _owned_by_someone_else(app, submission_id):
    with app.app_context():
        with Session() as session:
            session.get(classic.Submission, int(submission_id)).submitter_id = 900001
            session.commit()


def test_html_preview_is_open_to_moderators(app, authorized_client, html_source, mocker):
    """As legacy's /submit/<id>/view was. A moderator opening it is not the
    submitter previewing it, so it does not unlock Submit."""
    sid, _ = html_source
    _owned_by_someone_else(app, sid)
    mocker.patch.object(app.api, 'is_moderator', return_value=True)

    resp = authorized_client.get(f'/{sid}/preview/html/index.html')

    assert resp.status_code == status.OK
    with app.app_context():
        submission, _ = current_app.api.get_with_history(sid)
    assert not submission.submitter_confirmed_preview


def test_html_preview_is_closed_to_other_users(app, authorized_client, html_source, mocker):
    sid, _ = html_source
    _owned_by_someone_else(app, sid)
    mocker.patch.object(app.api, 'is_moderator', return_value=False)

    resp = authorized_client.get(f'/{sid}/preview/html/index.html')

    assert resp.status_code == status.FORBIDDEN
