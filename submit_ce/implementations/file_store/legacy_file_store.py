import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, List
from subprocess import Popen
from hashlib import md5
from base64 import urlsafe_b64encode

from arxiv.files import FileObj, LocalFileObj, FileDoesNotExist

from submit_ce.api import SubmissionFileStore
from submit_ce.domain import  Workspace
from submit_ce.domain.uploads import UploadLifecycleStates, UploadStatus, FileStatus
from submit_ce.domain.types import SubmitFile


class SecurityError(RuntimeError):
    """Something suspicious happened."""


class UserFile:
    pass


class LegacyFileStore(SubmissionFileStore):
    """
    Functions for storing and getting source files from the legacy /data/new filesystem.

    In the legacy system we use a shared volume. Inside of that, the first four digits of the ID we'll call a
    "shard id". The shard id is used to create a directory that in turn holds a directory for each id's files.

    For example, id ``65393829`` would have a directory at
    ``{LEGACY_FILESYSTEM_ROOT}/6539/65393829``.

    The directory contains:
     - a PDF that was compiled,
     - a ``source.log`` file (for the admins to look at)
     - a ``src`` directory that contains the actual file content.

    We also require the ability to set permissions on files and directories, and
    set the owner user and group.

    To use this, the following config parameters must be set:

    - ``LEGACY_FILESYSTEM_ROOT``: (see above)
    - ``LEGACY_FILESYSTEM_SOURCE_DIR_MODE``: permissions for directories; see
      :ref:`python:os.chmod`
    - ``LEGACY_FILESYSTEM_SOURCE_MODE``: permissions for files; see
      :ref:`python:os.chmod`
    - ``LEGACY_FILESYSTEM_SOURCE_UID``: uid for owner user (must exist)
    - ``LEGACY_FILESYSTEM_SOURCE_GID``: gid for owner group (must exist)
    - ``LEGACY_FILESYSTEM_SOURCE_PREFIX``

    Adapted from NG arxiv-submission-core 2024-09-19. Changed to a class, use of Pathlib.
    """

    def __init__(self,
                 root_dir: Path,
                 source_file_mode = 0o42775,
                 source_dir_mode = 0o42775,
                 source_uid = os.geteuid(),
                 source_gid = os.getegid(),
                 source_prefix = "src"
                 ):
        self.root_dir = root_dir
        """Path to the root directory of the file store shards."""
        self.source_file_mode = source_file_mode
        """Permission mode for files."""
        self.source_dir_mode = source_dir_mode
        """Permission mode for directories."""
        self.source_uid = source_uid
        """uid for owner user (must exist)."""
        self.source_gid = source_gid
        """gid for owner group (must exist)."""
        self.source_prefix = source_prefix
        """Prefix in the {root}/{shard}/{id} directory to store the source."""

    def get_source_file(self, submission_id: str, path: Path | str) -> FileObj:
        src_path = self._source_path(submission_id) / path
        if src_path.exists():
            return LocalFileObj(src_path)
        else:
            return FileDoesNotExist(str(src_path))

    def get_source_file_info(self, submission_id: str, path: Path | str) -> FileStatus:
        pass

    def store_source_file(self, submission_id: str, content: SubmitFile, chunk_size: int) -> FileStatus:
        return super().store_source_file(submission_id, content, chunk_size)

    def get_source_pacakge_checksum(self, submission_id: str) -> str:
        pass

    def get_preview(self, submission_id: str) -> FileObj:
        path = self._preview_path(submission_id)
        if path.exists():
            return LocalFileObj(path)
        else:
            return FileDoesNotExist(path.name)


    def is_available(self) -> bool:
        """Determine whether the filesystem is available."""
        return os.path.exists(self.root_dir)

    def get_workspace(self, submission_id: str, upload_id: str) -> Workspace:
        src_dir = self._source_path(submission_id)
        anc_dir = (src_dir / "anc")
        files: List[FileStatus] = []
        for path in Path(self._source_path(submission_id)).rglob("*"):
            stat = path.stat()
            files.append(FileStatus(str(path.relative_to(src_dir)),
                                    path.name,
                                    "unknown",
                                    stat.st_size,
                                    datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                                    anc_dir in path.parent.parents,
                                    []))

        return Workspace(
            identifier=submission_id,
            checksum='fake-checksum-asdf1234',
            size=sum([file.bytes for file in files]),
            started=datetime.now(),
            completed=datetime.now(),
            created=datetime.now(),
            modified=datetime.now(),
            status=UploadStatus.READY,
            lifecycle=UploadLifecycleStates.ACTIVE,
            locked=False,
            files=files,
            errors=[]
        )

    def delete_source_file(self, submission_id: str, path: Path|str) -> None:
        pass

    def delete_workspace(self, submission_id: str):
        src_dir = self._source_path(submission_id)
        shutil.rmtree(src_dir.absolute())

    def store_source_package(self,
                     submission_id: str,
                     content: SubmitFile,
                     chunk_size = 4096) -> str:
        """Store a source package for a submission."""
        # Make sure that we have a place to put the source files.
        package_path = self._source_package_path(submission_id)
        source_path = self._source_path(submission_id)
        if not os.path.exists(package_path):
            os.makedirs(os.path.split(package_path)[0])
        if not os.path.exists(source_path):
            os.makedirs(source_path)

        ["application/x-gzip", "application/gzip", "application/tar",
                    "application/x-tar", "application/tar+gzip",]
        with open(package_path, 'wb') as f:
            while True:
                chunk = content.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)

        self._unpack_tarfile(package_path, source_path)
        self._set_modes(package_path)
        self._set_modes(source_path)
        return self.get_source_checksum(submission_id)

    def store_preview(self, submission_id: str, content: IO[bytes],
                      chunk_size: int = 4096) -> str:
        """Store a preview PDF for a submission."""
        preview_path = self._preview_path(submission_id)
        if not os.path.exists(preview_path):
            os.makedirs(os.path.split(preview_path)[0])
        with open(preview_path, 'wb') as f:
            while True:
                chunk = content.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
        self._set_modes(preview_path)
        return self.get_preview_checksum(submission_id)

    def get_source_checksum(self, submission_id: str) -> str:
        """Get the checksum of the source package for a submission."""
        return self._get_checksum(self._source_package_path(submission_id))

    def does_source_exist(self, submission_id: str) -> bool:
        """Determine whether source has been deposited for a submission."""
        return os.path.exists(self._source_package_path(submission_id))

    def get_preview_checksum(self, submission_id: str) -> str:
        """Get the checksum of the preview PDF for a submission."""
        return self._get_checksum(self._preview_path(submission_id))

    def does_preview_exist(self, submission_id: str) -> bool:
        """Determine whether a preview has been deposited for a submission."""
        return self._preview_path(submission_id).exists()

    def _well_formed_submission_id(self, submission_id: str) -> None:
        """Checkt that submission_id is okay."""
        if len(submission_id) > 32 or not re.match(r'^\d+', submission_id):
            raise SecurityError('Submission ID is improperly typed. This is a security concern.')

    def _submission_path(self, submission_id: str) -> Path:
        """Gets classic filesystem structure is such as /{rootdir}/{first 4 digits of submission id}/{submission id}"""
        self._well_formed_submission_id(submission_id)
        shard_dir = self.root_dir / Path(str(submission_id)[:4])
        return shard_dir / Path(str(submission_id))

    def _source_path(self, submission_id: str) -> Path:
        """Get the source path for the submission_id"""
        return self._submission_path(submission_id) / self.source_prefix

    def _source_package_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / f'{submission_id}.tar.gz'

    def _preview_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / f'{submission_id}.pdf'

    def _get_checksum(self, path: str) -> str:
        hash_md5 = md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return urlsafe_b64encode(hash_md5.digest()).decode('utf-8')

    def _unpack_tarfile(self, tar_path: str, unpack_to: str) -> None:
        result = Popen(['tar', '-xzf', tar_path, '-C', unpack_to]).wait()
        if result != 0:
            raise RuntimeError(f'tar exited with {result}')

    def _chmod_recurse(self, parent: Path, dir_mode: int, file_mode: int,
                      uid: int, gid: int) -> None:
        """
        Recursively chmod and chown all directories and files.

        Parameters
        ----------
        parent : str
            Root directory for the operation (included).
        dir_mode : int
            Mode to set directories.
        file_mode : int
            Mode to set files.
        uid : int
            UID for chown.
        gid : int
            GID for chown.

        """
        if not os.path.isdir(parent):
            os.chown(parent, uid, gid)
            os.chmod(parent, file_mode)
            return

        for path, directories, files in os.walk(parent):
            for directory in directories:
                os.chown(os.path.join(path, directory), uid, gid)
                os.chmod(os.path.join(path, directory), dir_mode)
            for fname in files:
                os.chown(os.path.join(path, fname), uid, gid)
                os.chmod(os.path.join(path, fname), file_mode)
        os.chown(parent, uid, gid)
        os.chmod(parent, dir_mode)

    def _set_modes(self, path: str) -> None:
        dir_mode = self.source_dir_mode
        file_mode = self.source_file_mode
        source_uid = self.source_uid
        source_gid = self.source_gid
        self._chmod_recurse(path, dir_mode, file_mode, source_uid, source_gid)


    def makedirs(self, path: str) -> None:
        """Make directories recursively for ``path``."""
        abs_path = self.get_path_bare(path)
        if not os.path.exists(abs_path):
            os.makedirs(abs_path)

    def is_safe(self, workspace: Workspace, path: str,
                is_ancillary: bool = False, is_removed: bool = False,
                is_persisted: bool = False, is_system: bool = False,
                strict: bool = True) -> bool:
        """Determine whether a path is safe to use."""
        path_in_workspace = workspace.get_path(path, is_ancillary=is_ancillary,
                                               is_removed=is_removed,
                                               is_system=is_system)
        full_path = self.get_path_bare(path_in_workspace,
                                       is_persisted=is_persisted)
        try:
            self._check_safe(workspace, full_path, is_ancillary=is_ancillary,
                             is_removed=is_removed, is_persisted=is_persisted,
                             is_system=is_system, strict=strict)
        except ValueError:
            return False
        return True

    def _check_safe(self, workspace: Workspace, full_path: str,
                    is_ancillary: bool = False, is_removed: bool = False,
                    is_persisted: bool = False, is_system: bool = False,
                    strict: bool = True) -> None:
        if not strict or is_system:
            wks_full_path = self.get_path_bare(workspace.base_path,
                                               is_persisted=is_persisted)
        elif is_ancillary:
            wks_full_path = self.get_path_bare(workspace.ancillary_path,
                                               is_persisted=is_persisted)
        elif is_removed:
            wks_full_path = self.get_path_bare(workspace.removed_path,
                                               is_persisted=is_persisted)
        else:
            wks_full_path = self.get_path_bare(workspace.source_path,
                                               is_persisted=is_persisted)
        if wks_full_path not in full_path:
            raise ValueError(f'Not a valid path for workspace: {full_path}')

    def set_permissions(self, workspace: Workspace,
                        file_mode: int = 0o664, dir_mode: int = 0o775) -> None:
        """
        Set the file permissions for all uploaded files and directories.

        Applies to files and directories in submitter's upload source
        directory.
        """
        for u_file in workspace.iter_files(allow_directories=True):
            if u_file.is_directory:
                os.chmod(self.get_path(workspace, u_file), dir_mode)
            else:
                os.chmod(self.get_path(workspace, u_file), file_mode)

    def remove(self, workspace: Workspace, u_file: UserFile) -> None:
        """Remove a file."""
        src_path = self.get_path_bare(workspace.get_path(u_file), u_file.is_persisted)
        dest_path = self.get_path_bare(workspace.get_path(u_file.path, is_removed=True),
                                       is_persisted=u_file.is_persisted)
        self._check_safe(workspace, src_path, is_ancillary=u_file.is_ancillary,
                         is_persisted=u_file.is_persisted)
        self._check_safe(workspace, dest_path, is_removed=True,
                         is_persisted=u_file.is_persisted)
        self._make_way(dest_path)
        shutil.move(src_path, dest_path)

    def delete_all_source_files(self, submission_id: str) -> None:
        pass

    def delete_preview(self, submission_id: str) -> None:
        pass
