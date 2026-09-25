"""Tests for the HTML submission preview. [SUBMISSION-127]"""

from http import HTTPStatus as status

import pytest
from flask import current_app, request
from werkzeug.datastructures import MultiDict

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.document import DocMetadata, Document
from submit_ce.domain.event import ConfirmPreview, SetSourceFormat
from submit_ce.domain.exceptions import NoSuchDocument
from submit_ce.domain.uploads import SourceFormat
from submit_ce.implementations.file_store.mock_file_store import MockFileStore
from submit_ce.ui.controllers.new import final
from submit_ce.ui.controllers.new.preview import postprocess_html, preprocess_html

BASE = 'https://submit.example.org/1/preview/html/'
BASE_TAG = b'<base href="https://submit.example.org/1/preview/html/" />'
STAMP_TAG = b'<address><p>S</p></address>'
PNG = b'\x89PNG\r\n\x1a\n'
PAGE = (b'<html><head><title>T</title></head>'
        b'<body><img src="/image1.png"></body></html>')


def _preprocess(html: bytes) -> bytes:
    return preprocess_html(html, base_url=BASE, stamp='S', link_site='arxiv.org')


def test_preprocess_html_replaces_user_base_href():
    html = (b'<html><head><base href="http://example.com/"><title>T</title>'
            b'</head><body class="x">text</body></html>')
    assert _preprocess(html) == (
        b'<html><head>' + BASE_TAG + b'<title>T</title></head><body class="x">'
        + STAMP_TAG + b'text</body></html>')


@pytest.mark.parametrize('html, expected', [
    (b'<title>T</title><p>x</p>',
     b'<title>T</title>' + STAMP_TAG + BASE_TAG + b'<p>x</p>'),
    (b'<html><p>x</p></html>',
     b'<html>' + STAMP_TAG + BASE_TAG + b'<p>x</p></html>'),
    (b'<p>x</p>',
     STAMP_TAG + b'\n' + BASE_TAG + b'\n<p>x</p>'),
])
def test_preprocess_html_falls_back_like_legacy(html, expected):
    """Without <head> or <body>, legacy inserts after </title> or <html>,
    else at the top."""
    assert _preprocess(html) == expected


def test_preprocess_html_makes_absolute_links_relative():
    html = (b'<body><img src="/figs/a.png"><img src="//cdn.example.com/b.png">'
            b'<a href="/c.html">c</a></body>')
    out = _preprocess(html)
    assert b'src="figs/a.png"' in out
    assert b'src="cdn.example.com/b.png"' in out
    assert b'href="c.html"' in out


def test_preprocess_html_rewrites_old_arxiv_hosts():
    html = b'<body><a href="http://xxx.lanl.gov/abs/hep-th/9901001">x</a></body>'
    assert b'href="http://arxiv.org/abs/hep-th/9901001"' in _preprocess(html)


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
    assert resp.headers['Content-Security-Policy'] == 'sandbox allow-same-origin'
    assert resp.headers['Cache-Control'] == 'no-store'
    assert f'<base href="http://localhost/{sid}/preview/html/" />'.encode() in resp.data
    assert f'arXiv:submit/{sid}</a>'.encode() in resp.data
    assert b'src="image1.png"' in resp.data


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
    assert resp.headers['Content-Security-Policy'] == 'sandbox allow-same-origin'


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


def _postprocess(app, html: bytes) -> bytes:
    with app.test_request_context('/'):
        return postprocess_html(html, link_site='arxiv.org')


def test_postprocess_html_expands_list_lines(app, documents):
    out = _postprocess(app, b'<p>x</p>\nLIST:arXiv:1203.3462\n<p>y</p>\n')
    assert out.startswith(b'<p>x</p>\n<dl>\n') and out.endswith(b'</dl>\n<p>y</p>\n')
    assert b'<a href="https://arxiv.org/abs/1203.3462"' in out
    assert b'Gaussian Process Topic Models' in out
    assert b'Amrudin Agovic, Arindam Banerjee' in out
    assert b'Machine Learning (cs.LG)' in out
    assert b'We introduce a model.' not in out


def test_postprocess_html_abs_lines_include_the_abstract(app, documents):
    assert b'We introduce a model.' in _postprocess(app, b'ABS:1203.3462\n')


def test_postprocess_html_uses_the_version_asked_for(app, documents):
    out = _postprocess(app, b'LIST:arXiv:1203.3462v1\n')
    assert b'First version' in out
    assert b'<a href="https://arxiv.org/abs/1203.3462v1"' in out


def test_postprocess_html_reports_unknown_papers(app, documents):
    out = _postprocess(app, b'LIST:arXiv:9999.99999\n')
    assert out == b'<dl>\n<dd>9999.99999 [failed to get metadata for paper]</dd>\n</dl>\n'


def test_postprocess_html_escapes_metadata(app, documents):
    documents['1203.3462'].metadata[1].title = '<script>alert(1)</script>'
    out = _postprocess(app, b'LIST:1203.3462\n')
    assert b'<script>' not in out and b'&lt;script&gt;' in out


def test_postprocess_html_needs_directives_at_line_start(app, documents):
    """As arxiv-browse does, so the preview matches the announced paper."""
    html = b'  LIST:arXiv:1203.3462\n<p>see LIST:arXiv:1203.3462</p>\n'
    assert _postprocess(app, html) == html


def test_postprocess_html_links_report_numbers(app):
    out = _postprocess(app, b'(paper\n  REPORT-NO:SampleWS/2026/01\n)\n')
    assert out == (b'(paper\n<a href="https://arxiv.org/search/?searchtype=report_num'
                   b'&query=SampleWS%2F2026%2F01">SampleWS/2026/01</a>\n)\n')


def test_html_preview_expands_list_lines(authorized_client, html_source, documents):
    sid, store = html_source
    store._source[sid]['index.html'] = b'<html><body>\nLIST:arXiv:1203.3462\n</body></html>'
    resp = authorized_client.get(f'/{sid}/preview/html/index.html')
    assert b'Gaussian Process Topic Models' in resp.data
