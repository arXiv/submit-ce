from datetime import datetime
from typing import Optional, Tuple, List, IO
from pathlib import Path

from arxiv.files import FileObj

from submit_ce.api import SubmitApi, SubmissionFileStore
from submit_ce.api.compile_service import CompileService
from submit_ce.api.email_service import EmailService
from submit_ce.domain.uploads import SubmitFile
from submit_ce.domain.uploads import FileStatus, UploadStatus, UploadLifecycleStates
from submit_ce.domain import Event, Submission, License, User, Client, Workspace, \
    Moderator, Document
from submit_ce.domain.exceptions import NoSuchDocument
from submit_ce.domain.event.process import Result
from submit_ce.domain.process import ProcessStatus
from submit_ce.implementations.schedule import next_announcement_time, next_freeze_time


class NullCompilerService(CompileService):  # pragma: no cover

    def start_directives(self, submission: Submission, user: User, client: Client, api: 'SubmitApi',
                         source_package_id: Optional[str] = None) -> Result:
        pass

    def check_directives(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        pass

    def start_preflight(self, submission: Submission, user: User, client: Client, api: 'SubmitApi',
                        source_package_id: Optional[str] = None) -> Result:
        pass

    def check_preflight(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        pass

    def start_compile(self, submission: Submission, user: User, client: Client, api: 'SubmitApi',
                      source_package_id: Optional[str] = None) -> Result:
        pass

    def check(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        pass

    def is_available(self) -> bool:
        return False


class NullEmailService(EmailService):  # pragma: no cover

    def send_email(self,
                   to: list[str],
                   subject: str,
                   body: str,
                   reply_to: str,
                   cc: list[str] | None = None,
                   bcc: list[str] | None = None,
                   message_id: str = "",
                   references: str = "") -> tuple[str, str]:
        return ("", "")

    def is_available(self) -> bool:
        return False


class NullFileStore(SubmissionFileStore):  # pragma: no cover

    def get_workspace(self, submission_id: str) -> Optional[Workspace]:
        return Workspace(
            identifier=submission_id,
            checksum='null-store-checksum',
            size=1024,
            started=datetime.now(),
            completed=datetime.now(),
            created=datetime.now(),
            modified=datetime.now(),
            status=UploadStatus.READY,
            lifecycle=UploadLifecycleStates.ACTIVE,
            locked=False,
            files=[],
            errors=[],
        )

    def delete_workspace(self, submission_id: str):
        pass

    def get_source_file(self, submission_id: str, path: Path|str) -> FileObj:
        raise RuntimeError("No source file")

    def get_source_file_info(self, submission_id: str, path: Path|str) -> FileStatus:
        raise RuntimeError("No source file info")

    def delete_source_file(self, submission_id: str, path: Path|str) -> Optional[FileStatus]:
        pass

    def delete_all_source_files(self, submission_id: str) -> None:
        pass

    def store_source_file(self, submission_id: str,
                          content: SubmitFile,
                          chunk_size: int) -> FileStatus:
        raise RuntimeError("Not stored, this is from a NullFileStore")

    def store_source_package(self, submission_id: str, content: SubmitFile, chunk_size: int) -> list[FileStatus]:
        raise RuntimeError("Not stored, this is from a NullFileStore")

    def get_source_package_checksum(self, submission_id: str) -> str:
        return ""

    def does_source_exist(self, submission_id: str) -> bool:
        return False

    def build_source_package(self, submission_id: str) -> bytes:
        return b""

    def write_source_package(self, submission_id: str) -> None:
        pass

    def delete_source_package(self, submission_id: str) -> None:
        pass

    def get_source_package(self, submission_id: str) -> FileObj:
        from arxiv.files import FileDoesNotExist
        return FileDoesNotExist(f"{submission_id}.tar.gz")

    def get_full_submission_path(self, submission_id: str) -> str:
        return ""

    def get_full_submission_source_path(self, submission_id: str) -> str:
        return ""

    def get_full_outcome_path(self, submission_id: str) -> str:
        return ""

    def store_preview(self, submission_id: str, content: IO[bytes], chunk_size: int) -> str:
        return "not really stored, NullFileStore"

    def does_nostamp_preview_exist(self, submission_id: str) -> bool:
        return False

    def delete_nostamp_preview(self, submission_id: str) -> None:
        pass

    def store_compile_log(self, submission_id: str, content: IO[bytes], chunk_size: int = 4096) -> str:
        return "not really stored, NullFileStore"

    def uncompress_compile_tarball(self, submission_id: str) -> None:
        pass

    def store_directives(self, submission_id: str, content: dict) -> str:
        return "not really stored, NullFileStore"

    def get_directives(self, submission_id: str) -> FileObj:
        from arxiv.files import FileDoesNotExist
        return FileDoesNotExist(submission_id)

    def get_preview(self, submission_id: str) -> FileObj:
        from arxiv.files import FileDoesNotExist
        return FileDoesNotExist(submission_id)

    def delete_preview(self, submission_id: str) -> None:
        pass

    def delete_preflight(self, submission_id: str) -> None:
        pass

    def delete_directives(self, submission_id: str) -> None:
        pass

    def store_zzrm(self, submission_id: str, content: dict) -> None:
        pass

    def store_qa_metadata(self, submission_id: str, content: dict) -> None:
        pass

    def get_qa_artifact_info(self, submission_id: str):
        return {}, {}

    def get_preview_checksum(self, submission_id: str) -> str:
        return ""

    def does_preview_exist(self, submission_id: str) -> bool:
        return False

    def get_preflight(self, submission_id: str) -> FileObj:
        from arxiv.files import FileDoesNotExist
        return FileDoesNotExist(submission_id)

    def get_full_source_package_path(self, submission_id: str) -> str:
        return ""

    def get_full_preflight_package_path(self, submission_id: str) -> str:
        return ""

    def get_full_directives_package_path(self, submission_id: str) -> str:
        return ""

    def get_directives_checksum(self, submission_id: str) -> str:
        return ""

    def does_directives_exist(self, submission_id: str) -> bool:
        return False

    def store_user_decisions(self, submission_id: str, content: dict) -> str:
        return ""

    def get_user_decisions(self, submission_id: str) -> FileObj:
        from arxiv.files import FileDoesNotExist
        return FileDoesNotExist(submission_id)

    def delete_user_decisions(self, submission_id: str) -> None:
        pass

    def get_user_decisions_checksum(self, submission_id: str) -> str:
        return ""

    def does_user_decisions_exist(self, submission_id: str) -> bool:
        return False

    def get_compile_log(self, submission_id: str) -> FileObj:
        from arxiv.files import FileDoesNotExist
        return FileDoesNotExist(submission_id)

    def delete_compile_log(self, submission_id: str) -> None:
        pass

    def get_compile_log_checksum(self, submission_id: str) -> str:
        return ""

    def does_compile_log_exist(self, submission_id: str) -> bool:
        return False

    def get_compile_json(self, submission_id: str) -> FileObj:
        raise RuntimeError("No compile JSON")

    def delete_compile_json(self, submission_id: str) -> None:
        pass

    def get_compile_json_checksum(self, submission_id: str) -> str:
        return ""

    def does_compile_json_exist(self, submission_id: str) -> bool:
        return False

    def get_preflight_checksum(self, submission_id: str) -> str:
        return ""

    def does_preflight_exist(self, submission_id: str) -> bool:
        return False

    def get_request_log(self, submission_id: str) -> FileObj:
        raise RuntimeError("No request log")

    def delete_request_log(self, submission_id: str) -> None:
        pass

    def get_request_log_checksum(self, submission_id: str) -> str:
        return ""

    def does_request_log_exist(self, submission_id: str) -> bool:
        return False

    def get_source_log(self, submission_id: str) -> FileObj:
        raise RuntimeError("No source log")

    def delete_source_log(self, submission_id: str) -> None:
        pass

    def get_source_log_checksum(self, submission_id: str) -> str:
        return ""

    def does_source_log_exist(self, submission_id: str) -> bool:
        return False

    def is_available(self) -> bool:
        return False


class NullImplementation(SubmitApi):  # pragma: no cover
    """Submission that does as little as possible."""

    def get_compiler(self) -> CompileService:
        return NullCompilerService()

    def get_email_service(self) -> EmailService:
        return NullEmailService()

    def moderators_for_categories(
            self,
            categories: List[str],
            *,
            exclude_no_web_email: bool = True,
            exclude_no_email: bool = False,
            exclude_no_reply_to: bool = False,
    ) -> List[Moderator]:
        return []

    def get(self, submission_id: str) -> Submission:
        Submission(submission_id)

    def get_file_store(self) -> SubmissionFileStore:
        return NullFileStore()

    def licenses(self, active_only=True) -> List[License]:
        return []

    def categories_for_user(self, user_id: str) -> Optional[str]:
        return []

    def next_announcement_time(self, reference: Optional[datetime] = None) -> datetime:
        return next_announcement_time(reference)

    def next_freeze_time(self, reference: Optional[datetime] = None) -> datetime:
        return next_freeze_time(reference)

    def get_with_history(self, submission_id: str) -> Tuple[Submission, List[Event]]:
        return Submission(submission_id), []

    def load_submissions_for_user(self, user_id: int) -> List[Submission]:
        return []

    def load_documents_for_user(self, user_id: int) -> List[Document]:
        return []

    def get_document(self, paper_id: str) -> Document:
        raise NoSuchDocument(paper_id)

    def has_active_submission(self, paper_id: str,
                              exclude_submission_id: Optional[str] = None) -> bool:
        return False

    def save(self, *events: Event, submission_id: Optional[str] = None) -> Tuple[Submission, List[Event]]:
        submission = self.get_with_history(submission_id)
        for event in events:
            submission = event.apply(submission)

        return submission, events
