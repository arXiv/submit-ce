from datetime import timezone, datetime
from typing import Optional
from venv import logger
import httpx
from typing_extensions import override
from zoneinfo import ZoneInfo

from arxiv.base.config import ARXIV_BUSINESS_TZ

from submit_ce.domain import User, Client, Submission
from submit_ce.api.compile_service import CompileService
from submit_ce.domain.event.process import Result
from submit_ce.domain.process import ProcessStatus
import sys
from submit_ce.api.submit import SubmitApi
from submit_ce.implementations.compile.compile_at_gcp import PreflightOption, DEFAULT_MAX_APPEND_FILES, DEFAULT_MAX_TEX_FILES, DEFAULT_COMPILATION_TIMEOUT, compile_submission

sys.path.append('submit_ce/implementations/compile')

GCP_COMPILE_URL = "http://localhost:9001"

class GcpCompileAtLegacy(CompileService):
    """GCP Compile at legacy /data/new file store."""
    def __init__(self,
                base_submissions_dir: str,
                tex2pdf_url: str = GCP_COMPILE_URL,
                preflight: Optional[PreflightOption] = None,
                watermark_text: Optional[str] = None,
                max_append_files: int = DEFAULT_MAX_APPEND_FILES,
                max_tex_files: int = DEFAULT_MAX_TEX_FILES,
                timeout: int = DEFAULT_COMPILATION_TIMEOUT,
                ):
        self.tex2pdf_url = tex2pdf_url
        self.base_submissions_dir = base_submissions_dir
        self.preflight = preflight
        self.watermark_text = watermark_text
        self.max_append_files = max_append_files
        self.max_tex_files = max_tex_files
        self.timeout = timeout
        self.timezone = ARXIV_BUSINESS_TZ

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"tex2pdf_url={self.tex2pdf_url},"
                f"base_submissions_dir={self.base_submissions_dir}"
                )

    @override
    def start_preflight(self, submission: Submission, 
                  user: User, 
                  client: Client,
                  api: SubmitApi,
                  source_package_id: Optional[str] = None
    ) -> Result:
        pass

    @override
    def check_preflight(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        pass

    @override
    def start_compile(self, submission: Submission,
                      user: User, client: Client,
                      api: SubmitApi,
                      source_package_id: Optional[str] = None) -> Result:

        watermark = f"arXiv:submit/{submission.submission_id}"
        if submission.primary_classification:
            watermark += f" [{submission.primary_classification.category}]"

        watermark += f" {submission.submitted or datetime.now(ZoneInfo(self.timezone))}"

        utc_start_time = datetime.now(tz=timezone.utc)
        status, json_data = compile_submission(
            submission.submission_id,
            source_file="",  # falsy causes src dir to be used
            output_file="gcp_compile_output.tar.gz",
            tex2pdf_url=GCP_COMPILE_URL,
            base_submissions_dir=self.base_submissions_dir,
            preflight = self.preflight,
            watermark_text = watermark,
            )

        status = ProcessStatus.Status.PENDING
        match json_data["status"].lower():
            case "success":
                status = ProcessStatus.Status.SUCCEEDED
            case "failure"|"failed"|"fail":
                status = ProcessStatus.Status.FAILED

        pstatus = ProcessStatus(
            status=status,
            creator=user,
            created=datetime.now(timezone.utc),
            details=json_data
        )

        return Result(
            status=pstatus,
            duration_sec = json_data["total_time"],
            utc_start_time=utc_start_time,
            url=f"FAKE_URL_{__file__}"
        )

    @override
    def check(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        pass

    @override
    def is_available(self) -> bool:
        resp = httpx.get(self.tex2pdf_url)
        if resp.status_code == 200:
            return True
        logger.error(f"Healthcheck failed: service at '{self.tex2pdf_url}' responded with status {resp.status_code}")
        return False
