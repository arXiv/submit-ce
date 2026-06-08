"""Tests for :mod:`submit_ce.implementations.compile.compile_api_service`."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import httpx
import pytest

from submit_ce.implementations.compile import compile_api_service
from submit_ce.implementations.compile.compile_api_service import (
    CompileApiService,
    _auth_headers,
    _get_id_token,
)
from submit_ce.ui.config import settings


@pytest.fixture(autouse=True)
def clear_token_cache():
    """Prevent the module-level ID token cache from leaking between tests."""
    compile_api_service._ID_TOKEN_CACHE.clear()
    yield
    compile_api_service._ID_TOKEN_CACHE.clear()


def _mock_httpx_post(mocker, *, status_code, raise_for_status=None):
    """Patch httpx.Client so `with httpx.Client(...) as c: c.post(...)` yields
    a response with the given status_code."""
    resp = MagicMock(status_code=status_code)
    if raise_for_status is not None:
        resp.raise_for_status.side_effect = raise_for_status
    else:
        resp.raise_for_status.return_value = None
    mock_client = MagicMock()
    mock_client.__enter__.return_value.post.return_value = resp
    mocker.patch.object(compile_api_service.httpx, 'Client',
                        return_value=mock_client)
    return resp


def _mock_httpx_post_sequence(mocker, status_codes):
    """Cycle through `status_codes` across successive .post() calls (one per retry)."""
    responses = []
    for code in status_codes:
        r = MagicMock(status_code=code)
        r.raise_for_status.return_value = None
        responses.append(r)
    mock_client = MagicMock()
    mock_client.__enter__.return_value.post.side_effect = responses
    mocker.patch.object(compile_api_service.httpx, 'Client',
                        return_value=mock_client)
    return responses


def _mock_file_store():
    store = MagicMock()
    store.get_full_source_package_path.return_value = 'gs://bucket/src.tgz'
    store.get_full_preflight_package_path.return_value = 'gs://bucket/preflight.json'
    store.get_full_submission_source_path.return_value = 'gs://bucket/src/'
    store.get_full_outcome_path.return_value = 'gs://bucket/out/'
    store.get_full_submission_path.return_value = 'gs://bucket/sub'
    store.get_full_directives_package_path.return_value = 'gs://bucket/dir.json'
    return store


def _patch_current_app(mocker, store=None):
    """Replace current_app in the module with a stub whose api.get_file_store()
    returns the given store (default: a fresh _mock_file_store)."""
    mock_app = MagicMock()
    mock_app.api.get_file_store.return_value = store or _mock_file_store()
    mocker.patch.object(compile_api_service, 'current_app', mock_app)
    return mock_app


def _submission():
    s = MagicMock()
    s.submission_id = 'sub1'
    return s


# ------------------------------------------------------------ _get_id_token


def test_get_id_token_cache_hit_returns_cached_token(mocker):
    """Non-expired cache entry: no auth path runs, cached token returned."""
    audience = 'https://example.com'
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    compile_api_service._ID_TOKEN_CACHE[audience] = ('cached-tok', future)
    fetch = mocker.patch('google.oauth2.id_token.fetch_id_token')

    assert _get_id_token(audience) == 'cached-tok'
    fetch.assert_not_called()


def test_get_id_token_uses_impersonate_sa_when_set(mocker):
    """COMPILE_API_IMPERSONATE_SA set → use the impersonated_credentials path."""
    mocker.patch.object(settings, 'COMPILE_API_IMPERSONATE_SA',
                        'sa@x.iam.gserviceaccount.com')
    mocker.patch.object(compile_api_service.google.auth, 'default',
                        return_value=(MagicMock(), 'project'))
    target = mocker.patch.object(
        compile_api_service.impersonated_credentials, 'Credentials')
    mocker.patch.object(
        compile_api_service.impersonated_credentials, 'IDTokenCredentials',
        return_value=MagicMock(token='impersonated-tok'))
    fetch = mocker.patch('google.oauth2.id_token.fetch_id_token')

    assert _get_id_token('https://aud') == 'impersonated-tok'
    fetch.assert_not_called()
    target.assert_called_once()


def test_get_id_token_falls_back_to_fetch_id_token(mocker):
    """No impersonate SA → fetch_id_token is used."""
    mocker.patch.object(settings, 'COMPILE_API_IMPERSONATE_SA', '')
    fetch = mocker.patch('google.oauth2.id_token.fetch_id_token',
                         return_value='fetched-tok')

    assert _get_id_token('https://aud') == 'fetched-tok'
    fetch.assert_called_once()


def test_get_id_token_refetches_after_cache_expires(mocker):
    """Expired cache entry triggers a refetch."""
    audience = 'https://aud'
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    compile_api_service._ID_TOKEN_CACHE[audience] = ('stale-tok', past)
    mocker.patch.object(settings, 'COMPILE_API_IMPERSONATE_SA', '')
    fetch = mocker.patch('google.oauth2.id_token.fetch_id_token',
                         return_value='fresh-tok')

    assert _get_id_token(audience) == 'fresh-tok'
    fetch.assert_called_once()


# ------------------------------------------------------------ _auth_headers


def test_auth_headers_http_omits_authorization(mocker):
    mocker.patch.object(settings, 'COMPILE_API_URL', 'http://localhost:9001')
    headers = _auth_headers()
    assert 'Authorization' not in headers
    assert headers['accept'] == 'application/json'


def test_auth_headers_https_includes_bearer(mocker):
    mocker.patch.object(settings, 'COMPILE_API_URL', 'https://example.run.app')
    mocker.patch.object(compile_api_service, '_get_id_token',
                        return_value='tok-123')
    headers = _auth_headers()
    assert headers['Authorization'] == 'Bearer tok-123'


# ------------------------------------------------------------ __repr__


def test_repr_includes_compile_api_url(mocker):
    mocker.patch.object(settings, 'COMPILE_API_URL', 'http://test')
    assert 'tex2pdf_url=http://test' in repr(CompileApiService())


# ------------------------------------------------------------ check_* methods


def test_check_preflight_returns_succeeded():
    ps = CompileApiService().check_preflight('p1', MagicMock(), MagicMock())
    assert ps.status == ps.Status.SUCCEEDED


def test_check_returns_succeeded():
    ps = CompileApiService().check('p1', MagicMock(), MagicMock())
    assert ps.status == ps.Status.SUCCEEDED


def test_check_directives_returns_succeeded():
    ps = CompileApiService().check_directives('p1', MagicMock(), MagicMock())
    assert ps.status == ps.Status.SUCCEEDED


# ------------------------------------------------------------ is_available


def test_is_available_true_on_200(mocker):
    mocker.patch.object(compile_api_service.httpx, 'get',
                        return_value=MagicMock(status_code=200))
    assert CompileApiService().is_available() is True


def test_is_available_false_on_non_200(mocker):
    mocker.patch.object(compile_api_service.httpx, 'get',
                        return_value=MagicMock(status_code=503))
    assert CompileApiService().is_available() is False


def test_is_available_false_on_request_error(mocker):
    mocker.patch.object(compile_api_service.httpx, 'get',
                        side_effect=httpx.RequestError("boom"))
    assert CompileApiService().is_available() is False


# ------------------------------------------------------------ start_preflight


def test_start_preflight_success_returns_result(mocker):
    mocker.patch.object(settings, 'COMPILE_API_URL', 'http://localhost:9001')
    store = _mock_file_store()
    _patch_current_app(mocker, store)
    _mock_httpx_post(mocker, status_code=200)

    result = CompileApiService().start_preflight(
        _submission(), MagicMock(), MagicMock(), MagicMock())

    assert result.status.status == result.status.Status.SUCCEEDED
    store.get_full_source_package_path.assert_called_once_with('sub1')
    store.get_full_preflight_package_path.assert_called_once_with('sub1')


def test_start_preflight_retries_on_500_then_succeeds(mocker):
    mocker.patch.object(settings, 'COMPILE_API_URL', 'http://localhost:9001')
    mocker.patch.object(settings, 'COMPILE_API_MAX_RETRIES', 3)
    mocker.patch.object(compile_api_service.time, 'sleep')
    _patch_current_app(mocker)
    _mock_httpx_post_sequence(mocker, [500, 200])

    result = CompileApiService().start_preflight(
        _submission(), MagicMock(), MagicMock(), MagicMock())

    assert result.status.status == result.status.Status.SUCCEEDED


def test_start_preflight_raises_when_500_persists(mocker):
    mocker.patch.object(settings, 'COMPILE_API_URL', 'http://localhost:9001')
    mocker.patch.object(settings, 'COMPILE_API_MAX_RETRIES', 2)
    mocker.patch.object(compile_api_service.time, 'sleep')
    _patch_current_app(mocker)
    _mock_httpx_post(mocker, status_code=500)

    with pytest.raises(httpx.HTTPStatusError):
        CompileApiService().start_preflight(
            _submission(), MagicMock(), MagicMock(), MagicMock())


# ------------------------------------------------------------ start_compile


def test_start_compile_success_returns_result(mocker):
    mocker.patch.object(settings, 'COMPILE_API_URL', 'http://localhost:9001')
    store = _mock_file_store()
    _patch_current_app(mocker, store)
    _mock_httpx_post(mocker, status_code=200)

    result = CompileApiService().start_compile(
        _submission(), MagicMock(), MagicMock(), MagicMock())

    assert result.status.status == result.status.Status.SUCCEEDED
    store.get_full_submission_source_path.assert_called_once_with('sub1')
    store.get_full_outcome_path.assert_called_once_with('sub1')


def test_start_compile_raises_on_4xx(mocker):
    mocker.patch.object(settings, 'COMPILE_API_URL', 'http://localhost:9001')
    _patch_current_app(mocker)
    err = httpx.HTTPStatusError("400", request=MagicMock(), response=MagicMock())
    _mock_httpx_post(mocker, status_code=400, raise_for_status=err)

    with pytest.raises(httpx.HTTPStatusError):
        CompileApiService().start_compile(
            _submission(), MagicMock(), MagicMock(), MagicMock())


# ------------------------------------------------------------ start_directives


def test_start_directives_success_returns_result(mocker):
    mocker.patch.object(settings, 'COMPILE_API_URL', 'http://localhost:9001')
    store = _mock_file_store()
    _patch_current_app(mocker, store)
    _mock_httpx_post(mocker, status_code=200)

    result = CompileApiService().start_directives(
        _submission(), MagicMock(), MagicMock(), MagicMock())

    assert result.status.status == result.status.Status.SUCCEEDED
    store.get_full_submission_path.assert_called_once_with('sub1')
    store.get_full_directives_package_path.assert_called_once_with('sub1')


def test_start_directives_raises_when_500_persists(mocker):
    mocker.patch.object(settings, 'COMPILE_API_URL', 'http://localhost:9001')
    mocker.patch.object(settings, 'COMPILE_API_MAX_RETRIES', 2)
    mocker.patch.object(compile_api_service.time, 'sleep')
    _patch_current_app(mocker)
    _mock_httpx_post(mocker, status_code=500)

    with pytest.raises(httpx.HTTPStatusError):
        CompileApiService().start_directives(
            _submission(), MagicMock(), MagicMock(), MagicMock())
