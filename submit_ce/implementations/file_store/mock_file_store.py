"""In-memory `MockFileStore` for tests.

A drop-in `FileStore` for unit and integration tests that retains uploaded
content in process memory instead of persisting to GCS or the local
filesystem. Source packages (tar.gz / zip) are unpacked so that downstream
stages — review-files, process — can read individual files back via the
standard `FileStore` API.

Use it via `mocked_file_store(app)` from `submit_ce/ui/conftest.py`.
"""
import io
import json
import tarfile
import zipfile
from datetime import datetime, timezone
from typing import Dict, IO, Optional

from arxiv.files import FileDoesNotExist, FileObj
from yarl import URL

from submit_ce.domain.uploads import (
    FileStatus,
    SubmitFile,
    UploadLifecycleStates,
    UploadStatus,
    Workspace,
)
from submit_ce.implementations import NullFileStore


class _InMemoryFileObj(FileObj):
    """A FileObj backed by an in-memory bytes buffer."""

    def __init__(self, path: str, data: bytes) -> None:
        self._path = path
        self._data = data
        self._updated = datetime.now(timezone.utc)

    @property
    def name(self) -> str:
        return self._path

    def exists(self) -> bool:
        return True

    def open(self, mode: str = 'rb'):
        return io.BytesIO(self._data)

    @property
    def etag(self) -> str:
        return ""

    @property
    def size(self) -> int:
        return len(self._data)

    @property
    def updated(self) -> datetime:
        return self._updated

    def download_as_bytes(self) -> bytes:
        return self._data

    def download_as_text(self) -> str:
        return self._data.decode('utf-8')


def _file_status_from_bytes(path: str, data: bytes,
                            content_type: str = "application/octet-stream") -> FileStatus:
    return FileStatus(
        path=path,
        name=path.split('/')[-1],
        content_type=content_type,
        bytes=len(data),
        crc32c="",
        url=URL(f"memory:///{path}"),
        is_versioned=False,
        modified=datetime.now(timezone.utc),
    )


class MockFileStore(NullFileStore):
    """A NullFileStore variant with an in-memory store for tests.

    Unpacks tar.gz/zip source packages into an in-memory dict and serves
    them back via the standard FileStore API, so downstream stages
    (review-files, process) can read back the workspace contents.
    """

    def __init__(self) -> None:
        # per-submission file dicts: {submission_id: {path: bytes}}
        self._source: Dict[str, Dict[str, bytes]] = {}
        # single-blob slots
        self._preview: Dict[str, bytes] = {}
        self._nostamp_preview: Dict[str, bytes] = {}
        self._preflight: Dict[str, bytes] = {}
        self._directives: Dict[str, bytes] = {}
        self._user_decisions: Dict[str, bytes] = {}
        self._source_package: Dict[str, bytes] = {}

    # -------- source package / files --------

    def store_source_package(self, submission_id: str, content: SubmitFile,
                             chunk_size: int) -> list[FileStatus]:
        raw = content.stream.read()
        files: Dict[str, bytes] = {}
        try:
            with tarfile.open(fileobj=io.BytesIO(raw), mode='r:*') as tar:
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    f = tar.extractfile(member)
                    if f is not None:
                        files[member.name] = f.read()
        except tarfile.TarError:
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        files[info.filename] = zf.read(info)
            except zipfile.BadZipFile:
                # Not a recognized archive — store as a single file.
                files[content.filename] = raw

        bucket = self._source.setdefault(submission_id, {})
        bucket.update(files)
        return [_file_status_from_bytes(p, b) for p, b in files.items()]

    def store_source_file(self, submission_id: str, content: SubmitFile,
                          chunk_size: int) -> FileStatus:
        raw = content.stream.read()
        self._source.setdefault(submission_id, {})[content.filename] = raw
        return _file_status_from_bytes(content.filename, raw, content.content_type)

    def get_source_file(self, submission_id: str, path) -> FileObj:
        data = self._source.get(submission_id, {}).get(str(path))
        if data is None:
            return FileDoesNotExist(str(path))
        return _InMemoryFileObj(str(path), data)

    def delete_source_file(self, submission_id: str, path) -> Optional[FileStatus]:
        self._source.get(submission_id, {}).pop(str(path), None)
        return None

    def delete_all_source_files(self, submission_id: str) -> None:
        self._source.pop(submission_id, None)

    def does_source_exist(self, submission_id: str) -> bool:
        return bool(self._source.get(submission_id))

    def build_source_package(self, submission_id: str) -> bytes:
        """Re-tar the in-memory source files into a gzipped tarball."""
        files = self._source.get(submission_id, {})
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tar:
            for path, data in files.items():
                info = tarfile.TarInfo(name=path)
                info.size = len(data)
                info.mtime = int(datetime.now(timezone.utc).timestamp())
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    def write_source_package(self, submission_id: str) -> None:
        self._source_package[submission_id] = self.build_source_package(submission_id)

    def delete_source_package(self, submission_id: str) -> None:
        self._source_package.pop(submission_id, None)

    def get_source_package(self, submission_id: str) -> FileObj:
        data = self._source_package.get(submission_id)
        if data is None:
            return FileDoesNotExist(f"{submission_id}.tar.gz")
        return _InMemoryFileObj(f"{submission_id}.tar.gz", data)

    def get_workspace(self, submission_id: str) -> Optional[Workspace]:
        files = self._source.get(submission_id, {})
        statuses = [_file_status_from_bytes(p, b) for p, b in files.items()]
        now = datetime.now(timezone.utc)
        return Workspace(
            identifier=submission_id,
            checksum='mock-store-checksum',
            size=sum(len(b) for b in files.values()),
            started=now,
            completed=now,
            created=now,
            modified=now,
            status=UploadStatus.READY,
            lifecycle=UploadLifecycleStates.ACTIVE,
            locked=False,
            files=statuses,
            errors=[],
        )

    # -------- preview / preflight / directives / user_decisions --------

    def store_preview(self, submission_id: str, content: IO[bytes],
                      chunk_size: int = 4096) -> str:
        self._preview[submission_id] = content.read()
        return ""

    def store_nostamp_preview(self, submission_id: str, content: IO[bytes],
                              chunk_size: int = 4096) -> str:
        self._nostamp_preview[submission_id] = content.read()
        return ""

    def get_preview(self, submission_id: str) -> FileObj:
        data = self._preview.get(submission_id)
        return _InMemoryFileObj("preview.pdf", data) if data is not None else FileDoesNotExist(submission_id)

    def does_preview_exist(self, submission_id: str) -> bool:
        return submission_id in self._preview

    def delete_preview(self, submission_id: str) -> None:
        self._preview.pop(submission_id, None)

    def store_preflight(self, submission_id: str, content: dict) -> str:
        """Mock-only: directly inject a preflight blob.

        In production the compile service writes `gcp_preflight.json`
        out-of-band (e.g. to GCS); the abstract FileStore has no
        `store_preflight`. Tests use this hook so a `MockCompileMimesisPdf`
        can simulate preflight output.
        """
        self._preflight[submission_id] = json.dumps(content).encode('utf-8')
        return ""

    def get_preflight(self, submission_id: str) -> FileObj:
        data = self._preflight.get(submission_id)
        return _InMemoryFileObj("gcp_preflight.json", data) if data is not None else FileDoesNotExist(submission_id)

    def does_preflight_exist(self, submission_id: str) -> bool:
        return submission_id in self._preflight

    def delete_preflight(self, submission_id: str) -> None:
        self._preflight.pop(submission_id, None)

    def store_directives(self, submission_id: str, content: dict) -> str:
        self._directives[submission_id] = json.dumps(content).encode('utf-8')
        return ""

    def get_directives(self, submission_id: str) -> FileObj:
        data = self._directives.get(submission_id)
        return _InMemoryFileObj("directives.json", data) if data is not None else FileDoesNotExist(submission_id)

    def does_directives_exist(self, submission_id: str) -> bool:
        return submission_id in self._directives

    def delete_directives(self, submission_id: str) -> None:
        self._directives.pop(submission_id, None)

    def store_user_decisions(self, submission_id: str, content: dict) -> str:
        self._user_decisions[submission_id] = json.dumps(content).encode('utf-8')
        return ""

    def get_user_decisions(self, submission_id: str) -> FileObj:
        data = self._user_decisions.get(submission_id)
        return _InMemoryFileObj("user_decisions.json", data) if data is not None else FileDoesNotExist(submission_id)

    def does_user_decisions_exist(self, submission_id: str) -> bool:
        return submission_id in self._user_decisions

    def delete_user_decisions(self, submission_id: str) -> None:
        self._user_decisions.pop(submission_id, None)

    def is_available(self) -> bool:
        return True
