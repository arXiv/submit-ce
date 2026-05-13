import io
from datetime import timezone, datetime
from pathlib import Path
from typing import Optional
from typing_extensions import override
from submit_ce.api.compile_service import CompileService
from submit_ce.api.submit import SubmitApi
from submit_ce.domain.agent import Client, User
from submit_ce.domain.event.process import Result
from submit_ce.domain.process import ProcessStatus
from submit_ce.domain.submission import Submission


class MockCompileMimesisPdf(CompileService):
    """A `CompileService` that always succeeds by copying a fake PDF into place."""
    def __init__(self) -> None:
        super().__init__()

    @override
    def start_preflight(self,
            submission: Submission,
            user: User,
            client: Client,
            api: SubmitApi,
            source_package_id: Optional[str] = None,
    ) -> Result:
        return None

    @override
    def check_preflight(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        return None

    @override
    def start_compile(
        self,
        submission: Submission,
        user: User,
        client: Client,
        api: SubmitApi,
        source_package_id: Optional[str] = None,
    ) -> Result:
        from mimesis.providers.binaryfile import BinaryFile
        pdf = io.BytesIO(BinaryFile().document())
        api.get_file_store().store_preview(str(submission.submission_id),
                                           pdf,
                                           1024*4)
        return Result(
            status=ProcessStatus(
                status=ProcessStatus.Status.SUCCEEDED,
                creator=user,
                created=datetime.now(timezone.utc),
                details={"no_details": f"from {__file__}"}
                ),
            duration_sec=20,
            utc_start_time=datetime.now(timezone.utc),
            url=f"FAKE_URL_{__file__}"
            )

    @override
    def check(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        return ProcessStatus(
            status=ProcessStatus.Status.SUCCEEDED,
            creator=user,
            created=datetime.now(timezone.utc),
            details={"no_details": f"from {__file__}"}
        )

    @override
    def is_available(self) -> bool:
        return True
