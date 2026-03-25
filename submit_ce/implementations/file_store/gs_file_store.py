"""Implementation of `FileStore` using Google Storage (GS)."""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import IO, List
import logging
import tarfile

from arxiv.files import FileObj, FileDoesNotExist
from arxiv.files.object_store import GsObjectStore
from yarl import URL

from submit_ce.api import SubmissionFileStore
from submit_ce.domain import Workspace
from submit_ce.domain.uploads import UploadLifecycleStates, UploadStatus, FileStatus
from submit_ce.domain.types import SubmitFile

from google.cloud import storage

from submit_ce.implementations.file_store.file_store_mixin import FileStoreMixin


logger = logging.getLogger(__file__)



class GsFileStore(SubmissionFileStore, FileStoreMixin):
    """Functions for storing and getting source files using Google Storage (GS)."

    For keys this will use a simlar "shard id" used in the legacy system. The
    first four digits of the ID we'll call a "shard id". The shard id is used to
    create a directory that in turn holds a directory for each id's files.

    For example, id ``65393829`` would have a directory at
    ``{PREFIX}/6539/65393829``.

    To use this, the following config parameters must be set:

    - ``GS_BUCKET``: google storage bucket to use
    - ``GS_PREFIX``: a prefix to ues after the ``GS_BUCKET`` and before the shard id. May be ""

    2025-07-17: initial work

    """

    def __init__(self,
                 gs_bucket: str,
                 gs_prefix = "data/new",
                 source_prefix = "src",
                 ):
        self.gs_bucket = gs_bucket
        """GS to store the files."""
        self.gs_prefix = gs_prefix
        """Prefix in the {gs_bucket}/{shard}/{id} directory to store the source."""
        self.source_prefix = source_prefix
        """Prefix for source files"""

        if self.gs_prefix.startswith("/"):
            self.gs_prefix = self.gs_prefix[1:]

        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(self.gs_bucket)
        self.obj_store = GsObjectStore(self.bucket)

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"gs_bucket={self.gs_bucket},"
                f"gs_prefix={self.gs_prefix},"
                f"source_prefix={self.source_prefix},"
                )

    def _blob_to_file_status(self, submission_id, blob) -> FileStatus:
        src_dir = self._source_path(submission_id)
        anc_dir = src_dir / "anc"
        file_path = Path(blob.name)
        FileStatus(path=str(file_path.relative_to(src_dir)),
                   name=file_path.name,
                   content_type=blob.content_type,
                   bytes=blob.size,
                   crc32c=blob.crc32,
                   modified=blob.updated,
                   ancillary=anc_dir in file_path.parent.parents,
                   url=URL(f"gs://{blob.bucket.name}/{blob.name}#{blob.generation}"),
                   is_versioned=True,
                   errors=[]) # TODO not sure where to get errors from


    def get_source_file_info(self, submission_id: str, path: Path|str) -> FileStatus:
        blob = self.bucket.get_blob(str(self._source_path(submission_id) / path))
        if blob is None:
            raise FileNotFoundError(f"File {path} does not exist in source for submission {submission_id}")
        return self._blob_to_file_status(submission_id, blob)

    def delete_source_file(self, submission_id: str, path: Path|str) -> None:
        blob = self.bucket.get_blob(str(self._source_path(submission_id) / path))
        if blob is not None:
            blob.delete()

    def get_workspace(self, submission_id: str, upload_id="fake") -> Workspace:
        src_dir = self._source_path(submission_id)
        files: List[FileStatus] = []
        for blob in self.bucket.client.list_blobs(self.bucket, prefix=src_dir):
            files.append(self._blob_to_file_status(submission_id, blob))

        return Workspace(
            identifier=submission_id,
            checksum='fake-checksum-asdf1234',
            size=sum([file.bytes for file in files]),
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

    def store_source_file(self,
                     submission_id: str,
                     content: SubmitFile,
                     chunk_size: int) -> FileStatus:
        """Stores a file for a submisison."""
        blob = self.bucket.blob(str(self._source_path(submission_id) / content.filename))
        blob.upload_from_file(content.stream, content_type=content.content_type)
        return self._blob_to_file_status(submission_id, blob)

    def store_source_package(self,
                     submission_id: str,
                     content: SubmitFile,
                     chunk_size: int) -> str:
        """Store a source package for a submission."""
        files=[]
        src_dir = self._source_path(submission_id)

        with tarfile.open(fileobj=content.stream, mode="r:*") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                with tar.extractfile(member) as file:
                    blob = self.bucket.blob(str(src_dir / member.name))
                    blob.upload_from_file(file, size=member.size)
                    files.append( {"file":member.name, "bytes": member.size})

        return files

    def get_preview(self, submission_id: str) -> FileObj:
        preview_path = self._preview_path(submission_id)
        preview = self.bucket.blob(str(preview_path))
        if preview.exists():
            return preview
        else:
            return FileDoesNotExist(str(preview_path))

    def store_preview(self, submission_id: str,
                      content: IO[bytes],
                      chunk_size: int = 4096) -> str:
        """Store a preview PDF for a submission."""
        preview_path = self._preview_path(submission_id)
        blob = self.bucket.blob(preview_path)
        blob.upload_from_file(content)
        blob.reload()
        return blob.crc32c

    def get_source_checksum(self, submission_id: str) -> str:
        """Get the checksum of the source package for a submission."""
        return self._get_checksum(self._source_package_path(submission_id))

    def does_source_exist(self, submission_id: str) -> bool:
        """Determine whether source has been deposited for a submission."""
        return self.bucket.blob(str(self._source_package_path(submission_id))).exists()

    def get_preview_checksum(self, submission_id: str) -> str:
        """Get the checksum of the preview PDF for a submission."""
        return self._get_checksum(self._preview_path(submission_id))

    def does_preview_exist(self, submission_id: str) -> bool:
        """Determine whether a preview has been deposited for a submission."""
        return self.bucket.blob(str(self._preview_path(submission_id))).exists()

    def _get_checksum(self, path: str) -> str:
        item = self.bucket.blob(path)
        return item.crc32c

    def _submission_path(self, submission_id: str|str) -> Path:
        """Gets GS filesystem structure ex /{rootdir}/{first 4 digits of submission id}/{submission id}"""
        shard_dir = self.gs_prefix / Path(str(submission_id)[:4])
        return shard_dir / Path(str(submission_id))

    def _source_path(self, submission_id: int|str) -> Path:
        """Get the source path for the submission_id"""
        return self._submission_path(submission_id) / self.source_prefix

    def _source_package_path(self, submission_id: int|str) -> Path:
        return self._submission_path(submission_id) / f'{submission_id}.tar.gz'

    def _preview_path(self, submission_id: int|str) -> Path:
        return self._submission_path(submission_id) / f'{submission_id}.pdf'

    def get_source_file(self, submission_id: str, path: Path|str) -> FileObj:
        src_path = self._source_path(submission_id) / path
        blob = self.bucket.blob(str(src_path))
        if blob.exists():
            return blob
        else:
            return FileDoesNotExist(str(src_path))

    def get_source_package_checksum(self, submission_id: str) -> str:
        return self.get_source_checksum(submission_id)

    def delete_workspace(self, submission_id: str):
        blobs = self.bucket.list_blobs(prefix=str(self._source_path(submission_id)))
        for blob in blobs:
            blob.delete()

    def is_available(self) -> bool:
        """Determine whether the filesystem is available."""
        try:
            return self.bucket.exists()
        except Exception as ex:
            logger.error(f"Could not check if bucket exists: {ex}")
            return False


    def delete_all_source_files(self, submission_id: str) -> None:
        pass

    def delete_preview(self, submission_id: str) -> None:
        pass
