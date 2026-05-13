"""Implementation of `FileStore` using Google Storage (GS)."""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import IO, List, Optional
import json
import io
import logging
import tarfile
from typing_extensions import override

from arxiv.files import FileObj, FileDoesNotExist
from arxiv.files.object_store import GsObjectStore
from google.cloud.storage.blob import Blob
from yarl import URL

from submit_ce.api import SubmissionFileStore
from submit_ce.domain import Workspace
from submit_ce.domain.uploads import UploadLifecycleStates, UploadStatus, FileStatus
from submit_ce.domain.uploads import SubmitFile

from google.cloud import storage

from submit_ce.implementations.file_store.file_store_mixin import FileStoreMixin


logger = logging.getLogger(__file__)

# FileObj is designed so that Blob is a duck type of it.
# This same line is in arxiv.file.object_store
FileObj.register(Blob)

class GsFileStore(SubmissionFileStore, FileStoreMixin):
    """Functions for storing and getting source files using Google Storage (GS).

    For keys this will use a similar "shard id" used in the legacy system. The
    first four digits of the ID we'll call a "shard id". The shard id is used to
    create a directory that in turn holds a directory for each id's files.

    For example, id ``65393829`` would have a directory at
    ``{PREFIX}/6539/65393829``.

    To use this, the following config parameters must be set:

    - ``GS_BUCKET``: google storage bucket to use
    - ``GS_PREFIX``: a prefix to use after the ``GS_BUCKET`` and before the shard id. May be ""

    Pass a ``client`` to inject a pre-configured ``storage.Client`` If omitted,
    ``storage.Client()`` is used and credentials/endpoint are resolved from the
    environment as usual.

    2025-07-17: initial work
    """

    def __init__(self,
                 gs_bucket: str,
                 gs_prefix: str = "data/new",
                 source_prefix: str = "src",
                 client: Optional[storage.Client] = None,
                 ):
        self.gs_bucket = gs_bucket
        """GS bucket to store the files."""
        self.gs_prefix = gs_prefix
        """Prefix in the {gs_bucket}/{shard}/{id} directory to store the source."""
        self.source_prefix = source_prefix
        """Prefix for source files"""

        if self.gs_prefix.startswith("/"):
            self.gs_prefix = self.gs_prefix[1:]

        self.storage_client = client if client is not None else storage.Client()
        self.bucket = self.storage_client.bucket(self.gs_bucket)
        self.obj_store = GsObjectStore(self.bucket)


    @override
    def get_source_file_info(self, submission_id: str, path: Path|str) -> FileStatus:
        get_path = self._source_path(submission_id) / path
        self._check_path_safe(submission_id, get_path)
        blob = self.bucket.get_blob(str(get_path))
        if blob is None:
            raise FileNotFoundError(f"File {path} does not exist in source for submission {submission_id}")
        return self._blob_to_file_status(submission_id, blob)

    @override
    def delete_source_file(self, submission_id: str, path: Path|str) -> None:
        del_path = str(self._source_path(submission_id) / path)
        self._check_path_safe(submission_id, del_path)
        blob = self.bucket.get_blob(del_path)
        if blob is not None:
            blob.delete()

    @override
    def get_workspace(self, submission_id: str) -> Workspace:
        src_dir = self._source_path(submission_id)
        files: List[FileStatus] = []
        for blob in self.bucket.client.list_blobs(self.bucket, prefix=src_dir):
            files.append(self._blob_to_file_status(submission_id, blob))

        return Workspace(
            identifier=submission_id,
            checksum='fake-checksum-asdf1234',
            size=sum([file.bytes for file in files if file]),
            started=datetime.now(),  # TODO bogus
            completed=datetime.now(),  # TODO bogus
            created=datetime.now(),  # TODO bogus
            modified=datetime.now(),  # TODO bogus
            status=UploadStatus.READY,
            lifecycle=UploadLifecycleStates.ACTIVE,
            locked=False,
            files=files,
            errors=[]
        )

    @override
    def store_source_file(self,
                     submission_id: str,
                     content: SubmitFile,
                     chunk_size: int) -> FileStatus:
        """Stores a file for a submission."""
        store_at = str(self._source_path(submission_id) / content.filename)
        self._check_path_safe(submission_id, store_at)
        blob = self.bucket.blob(store_at)
        blob.upload_from_file(content.stream, content_type=content.content_type)
        blob.reload()
        return self._blob_to_file_status(submission_id, blob)

    @override
    def store_source_package(self,
                     submission_id: str,
                     content: SubmitFile,
                     chunk_size: int) -> str:
        """Store a source package for a submission."""

        # Upload the entire package file, because
        # - the legacy code seems to keep the gz current, and
        # - tex2pdf-api/preflight needs a path to a zip in a bucket.
        package_path = self._source_package_path(submission_id)
        package_blob = self.bucket.blob(str(package_path))
        content.stream.seek(0)
        package_blob.upload_from_file(content.stream, content_type=content.content_type)

        content.stream.seek(0)
        files=[]
        src_dir = self._source_path(submission_id)

        with tarfile.open(fileobj=content.stream, mode="r:*") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                with tar.extractfile(member) as file:
                    store_at = str(src_dir / member.name)
                    self._check_path_safe(submission_id, store_at)  # TODO this will be strange, what to do?
                    blob = self.bucket.blob(store_at)
                    blob.upload_from_file(file, size=member.size)
                    files.append({"file": member.name, "bytes": member.size})

        return files

    @override
    def get_preview(self, submission_id: str) -> FileObj:
        preview_path = self._preview_path(submission_id)
        preview = self.bucket.blob(str(preview_path))
        if preview.exists():
            return preview
        else:
            return FileDoesNotExist(str(preview_path))

    @override
    def store_preview(self, submission_id: str,
                      content: IO[bytes],
                      chunk_size: int = 4096) -> str:
        """Store a preview PDF for a submission."""
        preview_path = self._preview_path(submission_id)
        blob = self.bucket.blob(str(preview_path))
        blob.upload_from_file(content)
        blob.reload()
        return blob.crc32c

    @override
    def store_directives(self, submission_id: str, content: dict) -> str:
        """Store directives.json for a submission."""
        directives_path = self._directives_path(submission_id)
        blob = self.bucket.blob(str(directives_path))
        data = json.dumps(content).encode('utf-8')
        blob.upload_from_file(io.BytesIO(data), content_type='application/json')
        blob.reload()
        return blob.crc32c

    @override
    def get_source_checksum(self, submission_id: str) -> str:
        """Get the checksum of the source package for a submission."""
        return self._get_checksum(self._source_package_path(submission_id))

    @override
    def does_source_exist(self, submission_id: str) -> bool:
        """Determine whether source has been deposited for a submission."""
        return self.bucket.blob(str(self._source_package_path(submission_id))).exists()

    @override
    def get_preview_checksum(self, submission_id: str) -> str:
        """Get the checksum of the preview PDF for a submission."""
        return self._get_checksum(self._preview_path(submission_id))

    @override
    def does_preview_exist(self, submission_id: str) -> bool:
        """Determine whether a preview has been deposited for a submission."""
        return self.bucket.blob(str(self._preview_path(submission_id))).exists()

    @override
    def get_source_file(self, submission_id: str, path: Path|str) -> FileObj:
        src_path = str(self._source_path(submission_id) / path)
        self._check_path_safe(submission_id, src_path)
        blob = self.bucket.blob(src_path)
        if blob.exists():
            return blob
        else:
            return FileDoesNotExist(str(src_path))

    @override
    def get_source_pacakge_checksum(self, submission_id: str) -> str:
        return self.get_source_checksum(submission_id)

    @override
    def delete_workspace(self, submission_id: str) -> None:
        blobs = self.bucket.list_blobs(prefix=str(self._source_path(submission_id)))
        for blob in blobs:
            blob.delete()

    @override
    def is_available(self) -> bool:
        """Determine whether the filesystem is available."""
        try:
            return self.bucket.exists()
        except Exception as ex:
            logger.error(f"Could not check if bucket exists: {ex}")
            return False

    @override
    def delete_all_source_files(self, submission_id: str) -> None:
        blobs = self.bucket.list_blobs(prefix=str(self._source_path(submission_id)))
        for blob in blobs:
            blob.delete()

    @override
    def delete_preview(self, submission_id: str) -> None:
        preview_path = self._preview_path(submission_id)
        blob = self.bucket.blob(str(preview_path))
        if blob.exists():
            blob.delete()

    @override
    def get_directives(self, submission_id: str) -> FileObj:
        path = self._directives_path(submission_id)
        blob = self.bucket.blob(str(path))
        return blob if blob.exists() else FileDoesNotExist(str(path))

    @override
    def delete_directives(self, submission_id: str) -> None:
        blob = self.bucket.blob(str(self._directives_path(submission_id)))
        if blob.exists():
            blob.delete()

    @override
    def get_directives_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._directives_path(submission_id))

    @override
    def does_directives_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(str(self._directives_path(submission_id))).exists()

    @override
    def store_user_options(self, submission_id: str, content: dict) -> str:
        blob = self.bucket.blob(str(self._user_options_path(submission_id)))
        data = json.dumps(content).encode('utf-8')
        blob.upload_from_file(io.BytesIO(data), content_type='application/json')
        blob.reload()
        return blob.crc32c

    @override
    def get_user_options(self, submission_id: str) -> FileObj:
        path = self._user_options_path(submission_id)
        blob = self.bucket.blob(str(path))
        return blob if blob.exists() else FileDoesNotExist(str(path))

    @override
    def delete_user_options(self, submission_id: str) -> None:
        blob = self.bucket.blob(str(self._user_options_path(submission_id)))
        if blob.exists():
            blob.delete()

    @override
    def get_user_options_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._user_options_path(submission_id))

    @override
    def does_user_options_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(str(self._user_options_path(submission_id))).exists()

    @override
    def get_compile_log(self, submission_id: str) -> FileObj:
        path = self._compile_log_path(submission_id)
        blob = self.bucket.blob(str(path))
        return blob if blob.exists() else FileDoesNotExist(str(path))

    @override
    def delete_compile_log(self, submission_id: str) -> None:
        blob = self.bucket.blob(str(self._compile_log_path(submission_id)))
        if blob.exists():
            blob.delete()

    @override
    def get_compile_log_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._compile_log_path(submission_id))

    @override
    def does_compile_log_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(str(self._compile_log_path(submission_id))).exists()

    @override
    def get_compile_json(self, submission_id: str) -> FileObj:
        path = self._compile_json_path(submission_id)
        blob = self.bucket.blob(str(path))
        return blob if blob.exists() else FileDoesNotExist(str(path))

    @override
    def delete_compile_json(self, submission_id: str) -> None:
        blob = self.bucket.blob(str(self._compile_json_path(submission_id)))
        if blob.exists():
            blob.delete()

    @override
    def get_compile_json_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._compile_json_path(submission_id))

    @override
    def does_compile_json_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(str(self._compile_json_path(submission_id))).exists()

    @override
    def get_preflight(self, submission_id: str) -> FileObj:
        path = self._preflight_path(submission_id)
        blob = self.bucket.blob(str(path))
        return blob if blob.exists() else FileDoesNotExist(str(path))

    @override
    def delete_preflight(self, submission_id: str) -> None:
        blob = self.bucket.blob(str(self._preflight_path(submission_id)))
        if blob.exists():
            blob.delete()

    @override
    def get_preflight_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._preflight_path(submission_id))

    @override
    def does_preflight_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(str(self._preflight_path(submission_id))).exists()

    @override
    def get_request_log(self, submission_id: str) -> FileObj:
        path = self._request_log_path(submission_id)
        blob = self.bucket.blob(str(path))
        return blob if blob.exists() else FileDoesNotExist(str(path))

    @override
    def delete_request_log(self, submission_id: str) -> None:
        blob = self.bucket.blob(str(self._request_log_path(submission_id)))
        if blob.exists():
            blob.delete()

    @override
    def get_request_log_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._request_log_path(submission_id))

    @override
    def does_request_log_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(str(self._request_log_path(submission_id))).exists()

    @override
    def get_source_log(self, submission_id: str) -> FileObj:
        path = self._source_log_path(submission_id)
        blob = self.bucket.blob(str(path))
        return blob if blob.exists() else FileDoesNotExist(str(path))

    @override
    def delete_source_log(self, submission_id: str) -> None:
        blob = self.bucket.blob(str(self._source_log_path(submission_id)))
        if blob.exists():
            blob.delete()

    @override
    def get_source_log_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._source_log_path(submission_id))

    @override
    def does_source_log_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(str(self._source_log_path(submission_id))).exists()

    def _get_checksum(self, path: str) -> str:
        item = self.bucket.blob(path)
        return item.crc32c

    def _submission_path(self, submission_id: str) -> Path:
        """Gets GS filesystem structure ex /{rootdir}/{first 4 digits of submission id}/{submission id}"""
        shard_dir = self.gs_prefix
        return shard_dir / Path(submission_id)

    def _source_path(self, submission_id: str) -> Path:
        """Get the source path for the submission_id"""
        return self._submission_path(str(submission_id)) / self.source_prefix

    def _source_package_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / f'{submission_id}.tar.gz'

    def _preview_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / f'{submission_id}.pdf'

    def _directives_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'directives.json'

    def _user_options_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'user_options.json'

    def _compile_log_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'gcp_compile.log'

    def get_source_package_checksum(self, submission_id: str) -> str:
        return self.get_source_checksum(submission_id)

    def _compile_json_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'gcp_compile.json'

    def _full_base_path(self):
        return f'gs://{self.gs_bucket}'

    @override
    def get_full_submission_path(self, submission_id: str) -> Path:
        return f'{self._full_base_path()}/{self._submission_path(submission_id)}'

    @override
    def get_full_source_package_path(self, submission_id: str) -> str:
        return f'{self._full_base_path()}/{self._source_package_path(submission_id)}'

    @override
    def get_full_preflight_package_path(self, submission_id: str) -> str:
        return f'{self._full_base_path()}/{self._preflight_path(submission_id)}'

    @override
    def get_full_directives_package_path(self, submission_id: str) -> str:
        return f'{self._full_base_path()}/{self._directives_path(submission_id)}'

    def _request_log_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'gcp_request.log'

    def _source_log_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'source.log'

    @override
    def store_zzrm(self, submission_id: str, content: dict) -> None:
        path = self._source_path(submission_id) / '00README.json'
        blob = self.bucket.blob(str(path))
        data = json.dumps(content).encode('utf-8')
        blob.upload_from_file(io.BytesIO(data), content_type='application/json')

    def _blob_to_file_status(self, submission_id, blob) -> FileStatus:
        src_dir = self._source_path(submission_id)
        anc_dir = src_dir / "anc"
        file_path = Path(blob.name)
        return FileStatus(path=str(file_path.relative_to(src_dir)),
                   name=file_path.name,
                   content_type=blob.content_type or 'application/octet-stream',
                   bytes=blob.size,
                   crc32c=blob.crc32c,
                   modified=blob.updated,
                   ancillary=anc_dir in file_path.parent.parents,
                   url=URL(f"gs://{blob.bucket.name}/{blob.name}#{blob.generation}"),
                   is_versioned=True,
                   errors=[])  # TODO not sure where to get errors from

    def _check_path_safe(self, submission_id: int|str, path: str|Path) -> None:
        """Checks if a path is safely part of the files for `submission_id`.

        Raises an error if the path is not under the `self._source_path()` for
        `submission_id`
        """
        if not str(path).startswith(str(self._source_path(submission_id))):
            raise RuntimeError(f"Path {path} not part of submission_id {submission_id}")

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"gs_bucket={self.gs_bucket},"
                f"gs_prefix={self.gs_prefix},"
                f"source_prefix={self.source_prefix})")
