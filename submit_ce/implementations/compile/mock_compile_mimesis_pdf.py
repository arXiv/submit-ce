"""A `CompileService` for tests that always succeeds with a fake PDF."""
import io
from datetime import datetime, timezone
from typing import Optional

from typing_extensions import override

from tex2pdf_tools.preflight import (
    CompilerSpec,
    EngineType,
    LanguageType,
    MainProcessSpec,
    OutputType,
    ParsedTeXFile,
    PreflightResponse,
    PreflightStatus,
    PreflightStatusValues,
    ToplevelFile,
)

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
        # Inject a minimal preflight blob so review_files can detect
        # source_format=tex. Requires a MockFileStore with the
        # mock-only `store_preflight` hook.
        store = api.get_file_store()
        if hasattr(store, 'store_preflight'):
            preflight = PreflightResponse(
                status=PreflightStatus(key=PreflightStatusValues.success),
                detected_toplevel_files=[
                    ToplevelFile(
                        filename="main.tex",
                        process=MainProcessSpec(
                            compiler=CompilerSpec(
                                engine=EngineType.tex,
                                lang=LanguageType.tex,
                                output=OutputType.pdf,
                                postp=None,
                            ),
                        ),
                    ),
                ],
                tex_files=[ParsedTeXFile(filename="main.tex")],
                ancillary_files=[],
                maybe_used_files=[],
            )
            store.store_preflight(str(submission.submission_id), preflight.model_dump(mode='json'))
        return Result(
            status=ProcessStatus(
                status=ProcessStatus.Status.SUCCEEDED,
                creator=user,
                created=datetime.now(timezone.utc),
                details={"no_details": f"test object from {__file__}"}
            ),
            duration_sec=0,
            utc_start_time=datetime.now(timezone.utc),
            url=f"FAKE_URL_{__file__}"
        )

    @override
    def check_preflight(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        return None

    @override
    def start_directives(self,
            submission: Submission,
            user: User,
            client: Client,
            api: SubmitApi,
            source_package_id: Optional[str] = None,
    ) -> Result:
        api.get_file_store().store_directives(str(submission.submission_id), {})
        return Result(
            status=ProcessStatus(
                status=ProcessStatus.Status.SUCCEEDED,
                creator=user,
                created=datetime.now(timezone.utc),
                details={"no_details": f"test object from {__file__}"}
            ),
            duration_sec=0,
            utc_start_time=datetime.now(timezone.utc),
            url=f"FAKE_URL_{__file__}"
        )

    @override
    def check_directives(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        return ProcessStatus(
            status=ProcessStatus.Status.SUCCEEDED,
            creator=user,
            created=datetime.now(timezone.utc),
            details={"no_details": f"test object from {__file__}"}
        )

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

    @override
    def stamp(self, pdf_bytes: bytes, watermark_text: str,
              watermark_link: Optional[str] = None) -> bytes:
        """Pretend to stamp by prepending a marker.

        The marker lets tests distinguish the stamped preview from the
        unstamped fallback without inspecting PDF pixels, and keeps stamping
        offline/deterministic.
        """
        return b"STAMPED:" + pdf_bytes
