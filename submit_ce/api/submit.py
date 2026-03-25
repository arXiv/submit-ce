"""The central `SubmitAPI` for working with submissions.

Suggestions from Jonathan:
    
    1. DONE Allow load of submission without history, he is concerned the
    history may grow to be very large
    
    2. Event type maybe should be renamed. Command? Change?
    
    2.5 Maybe the History should be made of different types than the
       Command/Change?
    
    3. If save() has submission_id as `Optional` just to support
       start_submission. Maybe split that out to different function?
    
    4. NOT_AN_ACTION_ITEM: JY was expecting Submission to be an active object
       like SqlAlchemy but this much more like a simple data structure.
    
    5. NOT_AN_ACTION_ITEM: JY felt that SubmitAPI and FileStorage should be
       separate objects. I explained that SubmitAPI needed to lock the DB and
       file store while uploading files. FileStore is a separate object and the
       SubmitAPI has a FileStore.

    6. Add a compare-and-set feature to avoid race conditions.

Ideas after talking with Jonathan:
    
    1. Maybe there should be a DataStore and a FileStore. Or maybe a
    MetadataStore and FileStore? And then the SubmitAPI uses those?
    
    2. There are events that just change the metadata data and that is what the
    NG is designed around. And also events that do additional things: upload
    files, delete files, compile PDF, extract text, QA checks. The SubmitAPI
    needs to handle many of these since the metadata and file changes need to be
    coordinated. File upload is an example: the SubmitAPI has a FileManager and
    it should have an Upload event. The Upload event should have a BytesIO on it and
    the SubmitAPI should handle the whole "upload and record metadata"
    
    3. Is the NG style Event where the event knows how to change the submission
    good? Can we expand that to allow the event access to the SubmitAPI to do
    file uploads, file deletes, etc? How would we implement something like "no
    event can succeed before the arXiv TOS has been accepted?" (Yes, that would
    be easy to do, just check the event history in the validation step) 
    
    4. High on the list of priorities are testability and simplicity. 

    5. Testability of the design. Can we mock things? Can we do pytest fixtures?
    Response: Making pytest fixtures has been easy and makes test writing
    productive. Mocks have not yet been explored.
    
    6. What is evidence the design is going well?
   
    a. The `PubsubEventSubmitImplementation` was very easy to write and
    test. Auth will be done similar with a composed object. That will be good
    because all the auth logic will be in one file instead of spread across the
    app.

    7. Need a way for files to be retrieved via a bytestream or as just a gs URL.

"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Tuple, List, Optional

from submit_ce.api.compile_service import CompileService
from submit_ce.domain.types import SubmitFile
from submit_ce.domain import Submission, Event, User, Client, Workspace, License
from submit_ce.api.file_store import SubmissionFileStore


class SubmitApi(ABC):

    @abstractmethod
    def get(self, submission_id: str) -> Submission:
        """
        Gets a `Submission` object for the given `submission_id`.

        Parameters
        ----------
        submission_id : str
            Submission identifier.

        Returns
        -------
        :class:`.domain.submission.Submission`
            The current state of the submission.

        Raises
        -------
        :class:`arxiv.submission.exceptions.NoSuchSubmission`
            Raised when a submission with the passed ID cannot be found.

        """

    @abstractmethod
    def get_with_history(self, submission_id: int) -> Tuple[Submission, List[Event]]:
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
    def get_file_store(self) -> SubmissionFileStore:
        """
        Get a submission file store.

        Returns
        -------
            `SubmissionFileStore`
        """
        ...

    @abstractmethod
    def get_compiler(self) -> CompileService:
        """
        Gets a `CompileService` implementation object.

        Returns
        -------
            `CompileService`
        """
        ...

    # Ex what happens on a Command like CompileSource
    # What about longer commands? or things like compile source that may have a later result?
    # In legacy compile source is just synchronous.

    # What about other things in the QA system? Text extraction is kind of slow, usually 20 or 30 sec.
    # But some pathological cases, up to a timelimit of 5 or 10 minutes. Also, there are huge documents like 800 pages.

    # File upload is also more than just a basic metadata change.

    # On submit, send mail on submit and later if there is a problem send an email too.

    # Probably need a "status of submission and problems list" page. But this doesn't need to be designed right now

    # UploadCommand(file=uploaded_byteio, file_name="something.tgz", mime_type=mt, ...)
    # CompileSource()

    # def start_submission(self, start_cmd: StartCommand) -> Submission:
    #     ...
    #
    # def get_history(self, submission_id: str) -> List[Event]:
    #     ...


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

    @abstractmethod
    def upload(self, files: SubmitFile, submission_id: int, user: User, client: Client) -> Workspace:
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
        # TODO Make this just an Event+save()
        ...

    @abstractmethod
    def licenses(self, active_only=True) -> List[License]:
        """Gets a list of licenses that submitters can be set on the contents of submissions.

        Parameters
        ----------
        active_only : bool
           Whether to return only actively accepted license. If set to false,
           the list will include old licenses that are not currently accepted.
        """
        ...

    @abstractmethod
    def categories_for_user(self, user_id: str) -> list[str]:
        """Gets list of categories the user may submit to.

        If a user is authorized for all categories in a particular
        archive, the category names will be compressed to a wildcard
        ``archive.*`` representation. If the user is authorized for all
        categories in the system, this will be compressed to "*.*".
        """
        ...

    @abstractmethod
    def next_announcement_time(self, reference: Optional[datetime] = None) -> datetime:
        """Gets the next announce time. If `reference` is not passed, it does
        the next announce time from now.

        Parameters
        ----------
        reference : Optional[datetime]
           Time to calculate next announce for. If not set, use `now`

        Returns
        --------
        Time of next announce always TZ aware"""
        ...

    @abstractmethod
    def next_freeze_time(self, reference: Optional[datetime] = None) -> datetime:
        """Gets the next freeze time. If `reference` is not passed, it does
        the next freeze time from now.

        Parameters
        ----------
        reference : Optional[datetime]
           Time to calculate next freeze for. If not set, use `now`

        Returns
        --------
        Time of next freeze always TZ aware"""
        ...

    @abstractmethod
    def healthy(self)-> Tuple[bool, str]:
        """Return a message about this api that is safe to show the general
        public, raise a :class:`RuntimeError` if api is not configured correctly
        or services it depends on are not working.

        Returns
        -------
            bool
                `True` if this and all dependent services are healthy.
            str
                A message about the api that is safe to show to the general public.

        """
        ...
