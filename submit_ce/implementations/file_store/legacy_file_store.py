import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, List
from subprocess import Popen
from hashlib import md5
from base64 import urlsafe_b64encode
from typing_extensions import override

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

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(root_dir={self.root_dir})"

    @override
    def get_source_file(self, submission_id: str, path: Path | str) -> FileObj:
        src_path = self._source_path(submission_id) / path
        if src_path.exists():
            return LocalFileObj(src_path)
        else:
            return FileDoesNotExist(str(src_path))

    @override
    def get_source_file_info(self, submission_id: str, path: Path | str) -> FileStatus:
        if not isinstance(path, Path):
            path = Path(path)

        if path.is_absolute:
            raise ValueError("path must be relative to submission source")

        absolute_path = self._submission_path(submission_id) / path
        stat = absolute_path.stat()
        return FileStatus(
            name=path.name,
            path=str(absolute_path.relative_to(self._submission_path(submission_id))),
            content_type="test/plain",  # TODO mimetype
            bytes=stat.st_size,
            crc32c="FAKECRC32C",
            is_versioned=False,
            url=f"http://fakeurl.com/from/file/{__file__}",
            modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),  # TODO timezone is a guess
            ancillary=False,
            errors=[])


    @override
    def store_source_file(self, submission_id: str, content: SubmitFile, chunk_size: int) -> FileStatus:
        sub_path = self._submission_path(submission_id)
        sub_shard_path = os.path.split(sub_path)[0]
        if not os.path.exists(sub_shard_path):
            os.makedirs(sub_shard_path)
            self._set_modes(str(sub_shard_path))
        if not os.path.exists(sub_path):
            os.makedirs(sub_path)
            self._set_modes(str(sub_path))
        source_path = self._source_path(submission_id)
        if not os.path.exists(source_path):
            os.makedirs(source_path)
            self._set_modes(str(source_path))

        new_file = source_path / content.filename
        self._check_path(submission_id, source_path)
        with open(new_file, "wb") as fh:
            while True:
                if (chunk := content.read(chunk_size)):
                    fh.write(chunk)
                else:
                    break

        self._set_modes(str(new_file))
        return self.get_source_file_info(submission_id, new_file)



    @override
    def get_source_pacakge_checksum(self, submission_id: str) -> str:
        pass

    @override
    def get_preview(self, submission_id: str) -> FileObj:
        path = self._preview_path(submission_id)
        if path.exists():
            return LocalFileObj(path)
        else:
            return FileDoesNotExist(path.name)

    @override
    def is_available(self) -> bool:
        """Determine whether the filesystem is available."""
        return os.path.exists(self.root_dir)

    @override
    def get_workspace(self, submission_id: str) -> Workspace:
        src_dir = self._source_path(str(submission_id))
        anc_dir = (src_dir / "anc")
        files: List[FileStatus] = []
        for path in Path(self._source_path(str(submission_id))).rglob("*"):
            stat = path.stat()
            files.append(FileStatus(path=str(path.relative_to(src_dir)),
                                    name=path.name,
                                    content_type="unknown",
                                    bytes=stat.st_size,
                                    modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                                    url="http://example.com/fakeurl",
                                    crc32c="fakecrc32",
                                    ancillary=anc_dir in path.parent.parents,
                                    is_versioned=False
                                    ))

        return Workspace(
            identifier=str(submission_id),
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

    @override
    def delete_source_file(self, submission_id: str, path: Path|str) -> None:
        pass

    @override
    def delete_workspace(self, submission_id: str):
        src_dir = self._source_path(submission_id)
        shutil.rmtree(src_dir.absolute())

    @override
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

    @override
    def store_preview(self, submission_id: str, content: IO[bytes],
                      chunk_size: int = 4096) -> str:
        """Store a preview PDF for a submission."""
        preview_path = self._preview_path(submission_id)
        preview_dir = os.path.split(preview_path)[0]
        if not os.path.exists(preview_dir):
            os.makedirs(preview_dir)
        with open(preview_path, 'wb') as f:
            while True:
                chunk = content.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
        self._set_modes(preview_path)
        return self.get_preview_checksum(submission_id)

    @override
    def get_source_checksum(self, submission_id: str) -> str:
        """Get the checksum of the source package for a submission."""
        return self._get_checksum(self._source_package_path(submission_id))

    @override
    def does_source_exist(self, submission_id: str) -> bool:
        """Determine whether source has been deposited for a submission."""
        return os.path.exists(self._source_package_path(submission_id))

    @override
    def get_preview_checksum(self, submission_id: str) -> str:
        """Get the checksum of the preview PDF for a submission."""
        return self._get_checksum(self._preview_path(submission_id))

    @override
    def does_preview_exist(self, submission_id: str) -> bool:
        """Determine whether a preview has been deposited for a submission."""
        return self._preview_path(submission_id).exists()

    @override
    def delete_all_source_files(self, submission_id: str) -> None:
        pass

    @override
    def delete_preview(self, submission_id: str) -> None:
        path = self._preview_path(submission_id)
        if path.exists():
            path.unlink()

    @override
    def get_directives(self, submission_id: str) -> FileObj:
        path = self._directives_path(submission_id)
        return LocalFileObj(path) if path.exists() else FileDoesNotExist(path.name)

    @override
    def delete_directives(self, submission_id: str) -> None:
        path = self._directives_path(submission_id)
        if path.exists():
            path.unlink()

    @override
    def get_directives_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._directives_path(submission_id))

    @override
    def does_directives_exist(self, submission_id: str) -> bool:
        return self._directives_path(submission_id).exists()

    @override
    def get_compile_log(self, submission_id: str) -> FileObj:
        path = self._compile_log_path(submission_id)
        return LocalFileObj(path) if path.exists() else FileDoesNotExist(path.name)

    @override
    def delete_compile_log(self, submission_id: str) -> None:
        path = self._compile_log_path(submission_id)
        if path.exists():
            path.unlink()

    @override
    def get_compile_log_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._compile_log_path(submission_id))

    @override
    def does_compile_log_exist(self, submission_id: str) -> bool:
        return self._compile_log_path(submission_id).exists()

    @override
    def get_compile_json(self, submission_id: str) -> FileObj:
        path = self._compile_json_path(submission_id)
        return LocalFileObj(path) if path.exists() else FileDoesNotExist(path.name)

    @override
    def delete_compile_json(self, submission_id: str) -> None:
        path = self._compile_json_path(submission_id)
        if path.exists():
            path.unlink()

    @override
    def get_compile_json_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._compile_json_path(submission_id))

    @override
    def does_compile_json_exist(self, submission_id: str) -> bool:
        return self._compile_json_path(submission_id).exists()

    @override
    def get_preflight(self, submission_id: str) -> FileObj:
        path = self._preflight_path(submission_id)
        return LocalFileObj(path) if path.exists() else FileDoesNotExist(path.name)

    @override
    def delete_preflight(self, submission_id: str) -> None:
        path = self._preflight_path(submission_id)
        if path.exists():
            path.unlink()

    @override
    def get_preflight_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._preflight_path(submission_id))

    @override
    def does_preflight_exist(self, submission_id: str) -> bool:
        return self._preflight_path(submission_id).exists()

    @override
    def get_request_log(self, submission_id: str) -> FileObj:
        path = self._request_log_path(submission_id)
        return LocalFileObj(path) if path.exists() else FileDoesNotExist(path.name)

    @override
    def delete_request_log(self, submission_id: str) -> None:
        path = self._request_log_path(submission_id)
        if path.exists():
            path.unlink()

    @override
    def get_request_log_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._request_log_path(submission_id))

    @override
    def does_request_log_exist(self, submission_id: str) -> bool:
        return self._request_log_path(submission_id).exists()

    @override
    def get_source_log(self, submission_id: str) -> FileObj:
        path = self._source_log_path(submission_id)
        return LocalFileObj(path) if path.exists() else FileDoesNotExist(path.name)

    @override
    def delete_source_log(self, submission_id: str) -> None:
        path = self._source_log_path(submission_id)
        if path.exists():
            path.unlink()

    @override
    def get_source_log_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._source_log_path(submission_id))

    @override
    def does_source_log_exist(self, submission_id: str) -> bool:
        return self._source_log_path(submission_id).exists()

    def _well_formed_submission_id(self, submission_id: str) -> None:
        """Checkt that submission_id is okay."""
        if len(str(submission_id)) > 32 or not re.match(r'^\d+', str(submission_id)):
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

    def _directives_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'directives.json'

    def _compile_log_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'gcp_compile.log'

    def _compile_json_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'gcp_compile.json'

    def _preflight_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'gcp_preflight.json'

    def _request_log_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'gcp_request.log'

    def _source_log_path(self, submission_id: str) -> Path:
        return self._submission_path(submission_id) / 'source.log'

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

    def _check_path(self, submission_id, path:Path) -> None:
        """Raise a `RuntimeError` if path is not under submisison path."""
        if not isinstance(path, Path):
            raise RuntimeError("path must be of type pathlib.Path")

        path_resolved = path.resolve()
        sub_path = self._submission_path(submission_id)
        sub_path_resolved = sub_path.resolve()
        if not path_resolved.is_relative_to(sub_path_resolved):
            raise RuntimeError(f"path {path} resolves to {path_resolved} which is "\
                               f"not part of submission {submission_id} at "\
                               f"{sub_path_resolved}")
