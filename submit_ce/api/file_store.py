"""* TODO workspace snapshots
** make workspace snapshots
** get workspace snapshots
** list workspace snapshots

* What to do about workspaces and objects vs functions?
I kind of like the API being very much just functions because it makes
it direct to then make a REST API from it.

But a submission.file_store.worksapce would be nice in the python code.

Could I have both?  Like a file_store_convenience(file_store_impl) class that
returns a WorkspaceConvenience(file_store_impl, workspace_impl)

Seems doable.

* How to add worksapces?
Maybe just have an opitonal workspace_id on each call? If not set, it goes to the current worksapce.


"""
from __future__ import annotations
from abc import ABCMeta, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Optional, IO


from arxiv.files import FileObj

if TYPE_CHECKING:
    from submit_ce.domain import Workspace
    from submit_ce.domain.uploads import FileStatus
    from submit_ce.domain.types import SubmitFile


class SubmissionFileStore(metaclass=ABCMeta):
    @abstractmethod
    def get_workspace(self, submission_id: str) -> Optional[Workspace]:
        """Returns information about the source package."""
        pass

    @abstractmethod
    def delete_workspace(self, submission_id: str):
        """Deletes the source package."""
        pass

    @abstractmethod
    def get_source_file(self, submission_id: str, path: Path|str) -> FileObj:
        """Retrieve a file from the filesystem.

        path should be one of:
         - a pathless file: main.tex
         - a file inside src: figures/fig1.jpg
         """
        pass

    @abstractmethod
    def get_source_file_info(self, submission_id: str, path: Path|str) -> FileStatus:
        """Gets `FileInformation` about a file."""
        pass

    @abstractmethod
    def delete_source_file(self, submission_id: str, path: Path|str) -> None:
        """Deletes a file from the source package."""
        pass

    @abstractmethod
    def delete_all_source_files(self, submission_id: str) -> None:
        """Deletes all source files for a submission."""
        pass

    @abstractmethod
    def store_source_file(self, submission_id: str,
                          content: SubmitFile,
                          chunk_size: int) -> FileStatus:
        """Store a source package for a submission.

        If this is a single file, just save it. If it is a tgz of zip, unzip it.

        Overwrites any existing files with the same name.

        Returns information about the file."""
        pass

    @abstractmethod
    def store_source_package(self, submission_id: str, content: SubmitFile, chunk_size: int) -> str:
        """Store a source package (tgz, tar, gzip or zip) for a submission.

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
    def store_preview(self, submission_id: str, content: IO[bytes], chunk_size: int) -> str:
        """Store a preview PDF for a submission.

        Returns checksum"""
        pass

    @abstractmethod
    def get_preview(self, submission_id: str) -> FileObj:
        """Retrieve a PDF preview from the filesystem."""
        pass

    @abstractmethod
    def delete_preview(self, submission_id: str) -> None:
        """Deletes the preview file."""
        pass

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
