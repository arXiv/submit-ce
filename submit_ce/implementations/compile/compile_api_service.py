from datetime import datetime, timezone, timedelta
from typing import Optional
import logging
import httpx
import time
import urllib.parse
from typing_extensions import override

import google.auth
import google.auth.transport.requests
import google.oauth2.id_token
from google.auth import impersonated_credentials

from submit_ce.ui.config import settings

from submit_ce.domain import User, Client, Submission
from submit_ce.api.compile_service import CompileService
from submit_ce.domain.event.process import Result
from submit_ce.domain.process import ProcessStatus
from submit_ce.api.submit import SubmitApi

logger = logging.getLogger(__name__)

'''
The Preflight summary report is based on our best attempt to analyze the
(La)TeX submission files.

The Directives summary report is an attempt to prioritize and combine multiple
sources of information about the submission. This report currently takes into
account the submitter's preferences in the 00README directives file and the
preflight report. 

It eventually should include information from post-compilation sources.
ie: ?
'''

_ID_TOKEN_CACHE: dict[str, tuple[str, datetime]] = {}
_ID_TOKEN_TTL = timedelta(minutes=50)


def _get_id_token(audience: str) -> str:
    """Return a Google OIDC ID token for ``audience``.

    Uses the attached service account via the metadata server when
    ``COMPILE_API_IMPERSONATE_SA`` is empty (production on Cloud Run/GCE/GKE).
    Otherwise impersonates that SA using application-default credentials,
    which is the local-dev path.
    """
    cached = _ID_TOKEN_CACHE.get(audience)
    if cached and cached[1] > datetime.now(timezone.utc):
        return cached[0]

    auth_req = google.auth.transport.requests.Request()
    impersonate_sa = settings.COMPILE_API_IMPERSONATE_SA
    if impersonate_sa:
        source_creds, _ = google.auth.default()
        target_creds = impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=impersonate_sa,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        id_creds = impersonated_credentials.IDTokenCredentials(
            target_creds, target_audience=audience,
        )
        id_creds.refresh(auth_req)
        token = id_creds.token
    else:
        token = google.oauth2.id_token.fetch_id_token(auth_req, audience)

    _ID_TOKEN_CACHE[audience] = (token, datetime.now(timezone.utc) + _ID_TOKEN_TTL)
    return token


def _auth_headers() -> dict:
    headers = {'accept': 'application/json'}
    if settings.COMPILE_API_URL.startswith('https://'):
        headers['Authorization'] = f'Bearer {_get_id_token(settings.COMPILE_API_URL)}'
    return headers


class CompileApiService(CompileService):
    """Wrap calls to the tex2pdf-api service. See directive_manager.py for processing done in submit, on that data."""

    def __init__(self):
        pass


    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"tex2pdf_url={settings.COMPILE_API_URL}"
                )

    @override
    def start_preflight(self, 
            submission: Submission, 
            user: User, 
            client: Client,
            api: SubmitApi,
            source_package_id: Optional[str] = None,
    ) -> Result:
        logger.info("start_preflight, submission %s", submission.submission_id)

        '''
        curl -s -X POST 'http://localhost:9001/preflight
           ?source=gs://arxiv-sync-test-01/api-test/junk.tar.gz
           &dest=gs://arxiv-sync-test-01/api-test/junk.json'
        '''

        # tex2pdf's preflight endpoint takes a ``source`` URL pointing at a
        # tar.gz in the bucket and scans it for compiler/issue detection.
        # We rebuild the persisted ``<id>.tar.gz`` from the current ``src/``
        # directory before each preflight call so tex2pdf sees the user's
        # latest source. ``_common_file_change_execute`` deletes the same
        # path on every file event, so the build here is "build if needed,
        # not because we're scared" -- it's "always build the canonical
        # path from current source." Per file event the deletion is cheap
        # (one bucket call); per preflight click the build is one extraction
        # of N source files, so cost is linear in workspace size, not in
        # number of preceding file events.
        file_store = api.get_file_store()
        file_store.write_source_package(submission.submission_id)

        source_path = file_store.get_full_source_package_path(submission.submission_id)
        preflight_path = file_store.get_full_preflight_package_path(submission.submission_id)

        query_params = {
            'source': source_path,
            'dest': preflight_path,
        }
        headers = _auth_headers()

        url = f'{settings.COMPILE_API_URL}/preflight?{urllib.parse.urlencode(query_params)}'

        response = None
        for retry_attempt in range(settings.COMPILE_API_MAX_RETRIES):
            try:
                with httpx.Client(timeout=settings.COMPILE_API_PREFLIGHT_TIMEOUT) as client:
                    response = client.post(url, headers=headers)
                    logger.warning("Retry attempt %s", response)
                    if response.status_code == 500:
                        time.sleep(settings.COMPILE_API_RETRY_DELAY)
                    else:
                        break  # Exit the loop if the request succeeds
            except httpx.HTTPStatusError as exc:
                logger.error(f"HTTPX error occurred: {exc.response.text}")
                raise exc
            except httpx.RequestError as exc:
                logger.error(f"Request error occurred: {exc}")

        if response is None:
            raise RuntimeError("response is unexpectedly None")

        if response.status_code == 500:
           raise httpx.HTTPStatusError(f"HTTP error {response.status_code}", request=response.request, response=response)

        response.raise_for_status()

        return Result(
            status=ProcessStatus(
                status=ProcessStatus.Status.SUCCEEDED,
                creator=user,
                created=datetime.now(timezone.utc),
                details={'message': 'Preflight completed'}
            ),
            duration_sec=0,
            utc_start_time=datetime.now(timezone.utc),
            url="FAKE_URL_PREFLIGHT"
        )

    @override
    def check_preflight(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        logger.info("Checking preflight for process %s", process_id)
        return ProcessStatus(
            status=ProcessStatus.Status.SUCCEEDED,
            creator=user,
            created=datetime.now(timezone.utc),
            details={'message': 'Preflight check completed'}
        )

    @override
    def start_compile(self, submission: Submission,
                      user: User, client: Client,
                      api: SubmitApi,
                      source_package_id: Optional[str] = None) -> Result:
        logger.info("start_compile, submission %s", submission.submission_id)

        file_store = api.get_file_store()
        source_path = f"{file_store.get_full_submission_source_path(submission.submission_id)}"
        outcome_path = file_store.get_full_outcome_path(submission.submission_id)

        query_params = {
            'source': source_path,
            'dest': outcome_path,
        }
        headers = _auth_headers()

        url = f'{settings.COMPILE_API_URL}/convert?{urllib.parse.urlencode(query_params)}'

        response = None
        for retry_attempt in range(settings.COMPILE_API_MAX_RETRIES):
            try:
                with httpx.Client(timeout=settings.COMPILE_API_CONVERT_TIMEOUT) as client:
                    response = client.post(url, headers=headers)
                    if response.status_code == 500:
                        time.sleep(settings.COMPILE_API_RETRY_DELAY)
                    else:
                        break
            except httpx.HTTPStatusError as exc:
                logger.error(f"HTTPX error occurred: {exc.response.text}")
                raise exc
            except httpx.RequestError as exc:
                logger.error(f"Request error occurred: {exc}")

        if response is None:
            raise RuntimeError("response is unexpectedly None")

        response.raise_for_status()

        return Result(
            status=ProcessStatus(
                status=ProcessStatus.Status.SUCCEEDED,
                creator=user,
                created=datetime.now(timezone.utc),
                details={'message': 'Compile completed'}
            ),
            duration_sec=0,
            utc_start_time=datetime.now(timezone.utc),
            url="FAKE_URL_COMPILE"
        )

    @override
    def check(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        logger.info("Checking compilation for process %s", process_id)
        return ProcessStatus(
            status=ProcessStatus.Status.SUCCEEDED,
            creator=user,
            created=datetime.now(timezone.utc),
            details={'message': 'Compilation check completed'}
        )

    @override
    def is_available(self) -> bool:
        try:
            resp = httpx.get(settings.COMPILE_API_URL, timeout=1)
            return resp.status_code == 200
        except httpx.RequestError as exc:
            logger.error(f"Compile service at '{settings.COMPILE_API_URL}' is not available: {exc}")
            return False

    @override
    def stamp(self, pdf_bytes: bytes, watermark_text: str,
              watermark_link: Optional[str] = None) -> bytes:
        """Stamp a PDF via the tex2pdf ``/stamp/`` endpoint.

        The endpoint takes the PDF as a multipart upload plus the watermark
        text/link as query params, and returns the stamped PDF bytes in the
        response body (it does not write to the bucket). Non-2xx raises, so
        the caller falls back to the unstamped PDF.
        """
        query_params = {'watermark_text': watermark_text}
        if watermark_link:
            query_params['watermark_link'] = watermark_link
        # No trailing slash: the deployed service routes ``/stamp`` and 307-
        # redirects ``/stamp/`` -> ``/stamp`` (also downgrading to http, which
        # we must not follow with the auth token). Matches how /convert,
        # /preflight and /directives are called.
        url = f'{settings.COMPILE_API_URL}/stamp?{urllib.parse.urlencode(query_params)}'
        files = {'incoming': ('submission.pdf', pdf_bytes, 'application/pdf')}
        headers = _auth_headers()

        with httpx.Client(timeout=settings.COMPILE_API_CONVERT_TIMEOUT) as client:
            response = client.post(url, files=files, headers=headers)
        response.raise_for_status()
        return response.content

    @override
    def start_directives(self,
            submission: Submission,
            user: User,
            client: Client,
            api: SubmitApi,
            source_package_id: Optional[str] = None,
    ) -> Result:
        logger.info("start_directives, submission %s", submission.submission_id)

        submission_path = f"{api.get_file_store().get_full_submission_path(submission.submission_id)}/"
        directives_path = api.get_file_store().get_full_directives_package_path(submission.submission_id)

        query_params = {
            'source': submission_path,
            'dest': directives_path,
            'user_decisions_filename' : 'user_decisions.json',
        }
        headers = _auth_headers()

        logger.info(f"start_directives, query_params '{settings.COMPILE_API_URL}/directives?")
        logger.info("start_directives, query_params %s", query_params)
        url = f'{settings.COMPILE_API_URL}/directives?{urllib.parse.urlencode(query_params)}'

        response = None
        for retry_attempt in range(settings.COMPILE_API_MAX_RETRIES):
            try:
                with httpx.Client(timeout=settings.COMPILE_API_PREFLIGHT_TIMEOUT) as client:
                    response = client.post(url, headers=headers)
                    if response.status_code == 500:
                        time.sleep(settings.COMPILE_API_RETRY_DELAY)
                    else:
                        break
            except httpx.HTTPStatusError as exc:
                logger.error(f"HTTPX error occurred: {exc.response.text}")
                raise exc
            except httpx.RequestError as exc:
                logger.error(f"Request error occurred: {exc}")

        if response is None:
            raise RuntimeError("response is unexpectedly None")

        if response.status_code == 500:
            raise httpx.HTTPStatusError(f"HTTP error {response.status_code}", request=response.request, response=response)

        response.raise_for_status()

        return Result(
            status=ProcessStatus(
                status=ProcessStatus.Status.SUCCEEDED,
                creator=user,
                created=datetime.now(timezone.utc),
                details={'message': 'Directives completed'}
            ),
            duration_sec=0,
            utc_start_time=datetime.now(timezone.utc),
            url="FAKE_URL_DIRECTIVES"

        )
    @override
    def check_directives(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        logger.info("Checking preflight for process %s", process_id)
        return ProcessStatus(
            status=ProcessStatus.Status.SUCCEEDED,
            creator=user,
            created=datetime.now(timezone.utc),
            details={'message': 'Directives check completed'}
        )
