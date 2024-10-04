import os
from abc import ABCMeta, abstractmethod
from pathlib import Path
from typing import IO


class SubmissionFileStore(metaclass=ABCMeta):

    @abstractmethod
    def get_source_file(self, submission_id: str, path: Path) :
        """Retrieve a file from the filesystem.

        path should be one of:
         - a pathless file: main.tex
         - a file inside src: figures/fig1.jpg
         """
        ...


    @abstractmethod
    def store_source_package(self, submission_id: str, content, chunk_size) -> str:
        """Store a source package for a submission.

        Returns checksum"""
        pass

    @abstractmethod
    def get_source_pacakge_checksum(self, submission_id: str) -> str:
        """Get the checksum of the source package for a submission."""
        pass

    @abstractmethod
    def does_source_exist(self, submission_id: str) -> bool:
        """Determine whether source has been deposited for a submission."""
        pass



    @abstractmethod
    def store_preview(self, submission_id: str, content: IO[bytes]) -> str:
        """Store a preview PDF for a submission.

        Returns checksum"""
        pass

    @abstractmethod
    def get_preview(self, submission_id: str, path: Path):
        """Retrieve a file from the filesystem.

        path should be one of:
         - a pathless file: main.tex
         - a file inside src: figures/fig1.jpg
         """
        ...

    @abstractmethod
    def get_preview_checksum(self, submission_id: str) -> str:
        """Get the checksum of the preview PDF for a submission."""
        pass

    @abstractmethod
    def does_preview_exist(self, submission_id: str) -> bool:
        """Determine whether a preview has been deposited for a submission."""
        pass

    # @abstractmethod
    # def _validate_submission_id(self, submission_id: str) -> bool:
    #     """Just because we have a type check here does not mean that it is impossible
    #     for `submission_id` to be something other than an `int`. Since I'm
    #     paranoid, we'll do a final check here to eliminate the possibility that a
    #     (potentially dangerous) ``str``-like value sneaks by."""
    #     pass
    #
    # @abstractmethod
    # def _submission_path(self, submission_id: str) -> Path:
    #     """Gets classic filesystem structure is such as /{rootdir}/{first 4 digits of submission id}/{submission id}"""
    #     pass
    #
    # @abstractmethod
    # def _source_path(self, submission_id: str) -> Path:
    #     """Get the source path for the submission_id"""
    #     pass
    #
    # @abstractmethod
    # def _source_package_path(self, submission_id: str) -> Path:
    #     pass
    #
    # @abstractmethod
    # def _preview_path(self, submission_id: str) -> Path:
    #     pass
    #
    # @abstractmethod
    # def _get_checksum(self, path) -> str:
    #     pass
    #
    # @abstractmethod
    # def _unpack_tarfile(self, tar_path, unpack_to) -> None:
    #     pass
    #
    # @abstractmethod
    # def _chmod_recurse(self, parent, dir_mode, file_mode, uid, gid) -> None:
    #     """
    #     Recursively chmod and chown all directories and files.
    #
    #     Parameters
    #     ----------
    #     parent : str
    #         Root directory for the operation (included).
    #     dir_mode : int
    #         Mode to set directories.
    #     file_mode : int
    #         Mode to set files.
    #     uid : int
    #         UID for chown.
    #     gid : int
    #         GID for chown.
    #
    #     """
    #     pass
    #
    # @abstractmethod
    # def _set_modes(self, path) -> None:
    #     pass

    @abstractmethod
    def is_available(self) -> bool:
        """Determine whether the filesystem is available."""
        pass
