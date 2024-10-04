import os
from pathlib import Path
from typing import IO
from subprocess import Popen
from hashlib import md5
from base64 import urlsafe_b64encode

from submit_ce.file_store import SubmissionFileStore


class SecurityError(RuntimeError):
    """Something suspicious happened."""

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

    def get_source_file(self, submission_id: str, path: Path):
        pass

    def get_source_pacakge_checksum(self, submission_id: str) -> str:
        pass

    def get_preview(self, submission_id: str, path: Path):
        pass

    def is_available(self) -> bool:
        """Determine whether the filesystem is available."""
        return os.path.exists(self.root_dir)

    async def store_source_package(self,
                     submission_id: int,
                     content: IO[bytes],
                     chunk_size: int = 4096) -> str:
        """Store a source package for a submission."""
        # Make sure that we have a place to put the source files.
        package_path = self._source_package_path(submission_id)
        source_path = self._source_path(submission_id)
        if not os.path.exists(package_path):
            os.makedirs(os.path.split(package_path)[0])
        if not os.path.exists(source_path):
            os.makedirs(source_path)

        with open(package_path, 'wb') as f:
            while True:
                chunk = await content.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)

        self._unpack_tarfile(package_path, source_path)
        self._set_modes(package_path)
        self._set_modes(source_path)
        return self.get_source_checksum(submission_id)

    def store_preview(self, submission_id: int, content: IO[bytes],
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
        return os.path.exists(self._preview_path(submission_id))

    def _validate_submission_id(self, submission_id: int) -> None:
        """Just because we have a type check here does not mean that it is impossible
        for `submission_id` to be something other than an `int`. Since I'm
        paranoid, we'll do a final check here to eliminate the possibility that a
        (potentially dangerous) ``str``-like value sneaks by."""
        if not isinstance(submission_id, int):
            raise SecurityError('Submission ID is improperly typed. This is a security concern.')

    def _submission_path(self, submission_id: int) -> Path:
        """Gets classic filesystem structure is such as /{rootdir}/{first 4 digits of submission id}/{submission id}"""
        self._validate_submission_id(submission_id)
        shard_dir = self.root_dir / Path(str(submission_id)[:4])
        return shard_dir / Path(str(submission_id))

    def _source_path(self, submission_id: int) -> Path:
        """Get the source path for the submission_id"""
        return self._submission_path(submission_id) / self.source_prefix

    def _source_package_path(self, submission_id: int) -> Path:
        return self._submission_path(submission_id) / f'{submission_id}.tar.gz'

    def _preview_path(self, submission_id: int) -> Path:
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
