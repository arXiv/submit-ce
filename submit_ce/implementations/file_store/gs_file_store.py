"""Implementation of `FileStore` using Google Storage (GS)."""
from __future__ import annotations
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import IO, List
import logging
import tarfile

from arxiv.files import FileObj, FileDoesNotExist
from arxiv.files.object_store import GsObjectStore

from submit_ce.api import Upload, SubmissionFileStore
from submit_ce.api.domain.uploads import UploadLifecycleStates, UploadStatus, FileStatus
from submit_ce.api.file_store import SubmitFile

from google.cloud import storage

logger = logging.getLogger(__file__)

class SecurityError(RuntimeError):
    """Something suspicious happened."""

class Workspace():
    """Not yet implemented."""
    pass


class UserFile:
    pass


class GsFileStore(SubmissionFileStore):
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

    def get_workspace(self, submission_id: str) -> Upload:
        src_dir = self._source_path(submission_id)
        anc_dir = src_dir / "anc"
        files: List[FileStatus] = []
        for blob in self.obj_store.list(str(self._source_path(submission_id))):
            path = Path(blob.name)
            files.append(FileStatus(str(path.relative_to(src_dir)),
                                    path.name,
                                    "unknown",
                                    blob.size,
                                    blob.updated,
                                    anc_dir in path.parent.parents,
                                    []))

        return Upload(
            identifier=submission_id,
            checksum='fake-checksum-asdf1234',
            size=sum([file.size for file in files]),
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
        preview = self.bucket.blob(self._preview_path(submission_id))           
        if preview.exists():
            return preview
        else:
            return FileDoesNotExist(path.name)

    def store_preview(self, submission_id: str,
                      content: IO[bytes],
                      chunk_size: int = 4096) -> str:
        """Store a preview PDF for a submission."""
        preview_path = self._preview_path(submission_id)
        blob = self.bucket.blob(preview_path)
        blob.upload_from_file(content)
        blob.reload()
        return blob.crc32c

    def get_source_checksum(self, submission_id: int) -> str:
        """Get the checksum of the source package for a submission."""
        return self._get_checksum(self._source_package_path(submission_id))

    def does_source_exist(self, submission_id: int) -> bool:
        """Determine whether source has been deposited for a submission."""
        return os.path.exists(self._source_package_path(submission_id))

    def get_preview_checksum(self, submission_id: int) -> str:
        """Get the checksum of the preview PDF for a submission."""        
        return self._get_checksum(self._preview_path(submission_id))

    def does_preview_exist(self, submission_id: int) -> bool:
        """Determine whether a preview has been deposited for a submission."""
        return self._preview_path(submission_id).exists()

    def _get_checksum(self, path: str) -> str:
        item = self.bucket.blob(path)
        return item.crc32c
                
    def _submission_path(self, submission_id: int|str) -> Path:
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

    
    ############################## TODO ##############################
    def get_source_file(self, submission_id: str):  # TODO implement
        # TODO implement get_source_file
        pass

    def get_source_pacakge_checksum(self, submission_id: str) -> str:  # TODO implement
        # TODO implement get_source_pacakge_checksum
        pass

    def delete_workspace(self, submission_id: str):  # TODO implement
        src_dir = self._source_path(submission_id)
        shutil.rmtree(src_dir.absolute())


    def remove(self, workspace: Workspace, u_file: UserFile) -> None:  # TODO implement
        """Remove a file."""
        src_path = self.get_path_bare(workspace.get_path(u_file), u_file.is_persisted)
        dest_path = self.get_path_bare(workspace.get_path(u_file.path, is_removed=True),
                                       is_persisted=u_file.is_persisted)
        # self._check_safe(workspace, src_path, is_ancillary=u_file.is_ancillary,
        #                  is_persisted=u_file.is_persisted)
        # self._check_safe(workspace, dest_path, is_removed=True,
        #                  is_persisted=u_file.is_persisted)
        # self._make_way(dest_path)
        # shutil.move(src_path, dest_path)

    def is_available(self) -> bool:  # TODO implement
        """Determine whether the filesystem is available."""
        # TODO implement is_available
        pass

        
    # def _check_safe(self, workspace: Workspace, full_path: str,  # TODO implement
    #                 is_ancillary: bool = False, is_removed: bool = False,
    #                 is_persisted: bool = False, is_system: bool = False,
    #                 strict: bool = True) -> None:
    #     if not strict or is_system:
    #         wks_full_path = self.get_path_bare(workspace.base_path,
    #                                            is_persisted=is_persisted)
    #     elif is_ancillary:
    #         wks_full_path = self.get_path_bare(workspace.ancillary_path,
    #                                            is_persisted=is_persisted)
    #     elif is_removed:
    #         wks_full_path = self.get_path_bare(workspace.removed_path,
    #                                            is_persisted=is_persisted)
    #     else:
    #         wks_full_path = self.get_path_bare(workspace.source_path,
    #                                            is_persisted=is_persisted)
    #     if wks_full_path not in full_path:
    #         raise ValueError(f'Not a valid path for workspace: {full_path}')
