from datetime import datetime, timezone
from typing import Optional
import logging
import httpx
import urllib.parse
from typing_extensions import override
from flask import current_app

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

class CompileApiService(CompileService):
    """Local Compile Service implementation."""

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

        # This tgz may be older than the files in the src dir, 
        #   since submit 2.0 does not yet regenerate after file changes.
        # We could:
        #   - update tex2pdf-api to build from the src dir
        #   - update tex2pdf-api to support rezip
        #   - check file dates and rezip locally, maybe on user request
        source_path = current_app.api.get_file_store().get_full_source_package_path(submission.submission_id)

        preflight_path = current_app.api.get_file_store().get_full_preflight_package_path(submission.submission_id)

        query_params = {
            'source': source_path,
            'dest': preflight_path,
        }
        headers = {
            'accept': 'application/json',
        }

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
            url="FAKE_URL_LOCAL_PREFLIGHT"
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

        logger.info("Compilation started for submission %s", submission.submission_id)
        return Result(
            status=ProcessStatus(
                status=ProcessStatus.Status.SUCCEEDED,
                creator=user,
                created=datetime.now(timezone.utc),
                details={'message': 'Local compilation completed'}
            ),
            duration_sec=0,
            utc_start_time=datetime.now(timezone.utc),
            url="FAKE_URL_LOCAL_COMPILE"
        )

    @override
    def check(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        logger.info("Checking local compilation for process %s", process_id)
        return ProcessStatus(
            status=ProcessStatus.Status.SUCCEEDED,
            creator=user,
            created=datetime.now(timezone.utc),
            details={'message': 'Local compilation check completed'}
        )

    @override
    def is_available(self) -> bool:
        try:
            resp = httpx.get(self.tex2pdf_url, timeout=1)
            return resp.status_code == 200
        except httpx.RequestError as exc:
            logger.error(f"Local compile service at '{self.tex2pdf_url}' is not available: {exc}")
            return False

    @override
    def convert_preflight_to_directives(self, contents: str) -> str:
        return None
