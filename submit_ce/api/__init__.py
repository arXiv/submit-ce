"""Core persistence methods for submissions and submission events."""

from abc import ABC, abstractmethod, ABCMeta
from io import BytesIO
from pathlib import Path
from typing import Tuple, List, Optional, Sequence, Protocol, IO

from submit_ce.api.domain import Submission, License, User, Client, Agent
from submit_ce.api.domain.event import Event

__all__ = ["SubmitApi"]

from submit_ce.api.domain.uploads import Upload


class SubmitFile(Protocol):
    """Represents a file for a submission."""
    filename: str
    """Name of the file as provided by the client."""
    content_type: str
    """The MIME type of the file as provided by the client."""
    stream: BytesIO
    """File contents as provided by the client."""



class SubmissionFileStore(metaclass=ABCMeta):
    @abstractmethod
    def get_workspace(self, submission_id: str) -> Optional[Upload]:
        """Returns information about the source package."""
        pass

    @abstractmethod
    def get_source_file(self, submission_id: str, path: Path) -> BytesIO:
        """Retrieve a file from the filesystem.

        path should be one of:
         - a pathless file: main.tex
         - a file inside src: figures/fig1.jpg
         """
        pass

    @abstractmethod
    def store_source_package(self, submission_id: str, content: SubmitFile, chunk_size) -> str:
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


class SubmitApi(ABC):
    @abstractmethod
    def load(self, submission_id: int) -> Tuple[Submission, List[Event]]:
        """
        Load a submission and its history.

        This loads all events for the submission, and generates the most up-to-date representation based on
        those events.

        Parameters
        ----------
        submission_id : str
            Submission identifier.

        Returns
        -------
        :class:`.domain.submission.Submission`
            The current state of the submission.
        list
            Items are :class:`.Event` instances, in order of their occurrence.

        Raises
        ------
        :class:`arxiv.submission.exceptions.NoSuchSubmission`
            Raised when a submission with the passed ID cannot be found.

        """
        ...

    @abstractmethod
    def load_submissions_for_user(self, user_id: int) -> List[Submission]:
            """
            Load active :class:`.domain.submission.Submission` for a specific user.

            Parameters
            ----------
            user_id : int
                Unique identifier for the user.

            Returns
            -------
            list
                Items are :class:`.domain.submission.Submission` instances.

            """
            ...

    @abstractmethod
    def get_file_store(self, workspace_id) -> SubmissionFileStore:
        """
        Get a submission file store for a workspace.

        Parameters
        ----------
        workspace_id :

        Returns
        -------
            `SubmissionFileStore`
        """
        ...

    @abstractmethod
    def save(self, *events: Event, submission_id: Optional[int] = None) \
            -> Tuple[Submission, List[Event]]:
            """
            Commit a set of new :class:`.Event` instances for a submission.

            This will persist the events to the database, along with the final
            state of the submission, and generate external notification(s) on the
            appropriate channels.

            Parameters
            ----------
            events : :class:`.Event`
                Events to apply and persist.
            submission_id : int
                The unique ID for the submission, if available. If not provided, it is
                expected that ``events`` includes a :class:`.CreateSubmission`.

            Returns
            -------
            :class:`arxiv.submission.domain.submission.Submission`
                The state of the submission after all events (including rule-derived
                events) have been applied. Updated with the submission ID, if a
                :class:`.CreateSubmission` was included.
            list
                A list of :class:`.Event` instances applied to the submission. Note
                that this list may contain more events than were passed, if event
                rules were triggered.

            Raises
            ------
            :class:`arxiv.submission.exceptions.NoSuchSubmission`
                Raised if ``submission_id`` is not provided and the first event is not
                a :class:`.CreateSubmission`, or ``submission_id`` is provided but
                no such submission exists.
            :class:`.InvalidEvent`
                If an invalid event is encountered, the entire operation is aborted
                and this exception is raised.
            :class:`.SaveError`
                There was a problem persisting the events and/or submission state
                to the database.

            """
            ...

    def upload(self, files: SubmitFile, submission_id: int, user: Agent, client: Client) -> Upload:
        """Uploads a file to an existing submission.

        Saves the `file` to storage and updates the state of the submission.
        Parameters
        ----------
        files : :class:`.FileUpload`
            The file to be uploaded.
        submission_id : int
            Identifier for the submission.
        user : :class:`.User`
            User making the upload
        client : :class:`.Client`
            Client tool making the upload.
        """
        # TODO Should this just be an Event+save()?
        ...

    def licenses(self, active_only=True) -> List[License]:
        """Gets a list of licenses that submitters can be set on the contents of submissions.

        Parameters
        ----------
        active_only : bool
           Whether to return only actively accepted license. If set to false, the list will include old licenses that
           are not currently accepted.
        """
        ...


    def categories_for_user(self, user_id: str) -> Optional[str]:
        """Gets list of categories the user may submit to."""
        ...
