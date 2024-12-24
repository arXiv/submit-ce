from abc import ABC, abstractmethod
from typing import Tuple, List, Optional

from submit_ce.api.domain import Submission, Event, Agent, Client, Upload, License
from submit_ce.api.file_store import SubmissionFileStore, SubmitFile


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

    #SubmissionHistory = List[Events]

    """Suggestions from Jonathan:
    
    1. Allow load of submission without history, he is concerned the history may grow to be very large
    2. Event maybe should be renamed? Command? Change? Maybe the History should be made of different types
       than the Command/Change?
    3. If save() has submission_id as optional just to support start_submission maybe split that out to 
       different function?
    4. JY was expecting Submission to be an active object like SqlAlchemy but this much more
       like a simple data structure. 
    5. JY felt that SubmitAPI and FileStorage should be separate objects. I explained that SubmitAPI
       needed to lock the DB and file store while uploading files. So the SubmitAPI has a FileStore.
    
    Ideas after talking with Jonathan:
    
    1. Maybe there should be a DataStore and a FileStore. Or maybe a MetadataStore and FileStore? And then the 
    SubmitAPI uses those? Maybe something to send PubSub like messages?
    
    2. It is clear to me that there are events that just change the metadata data and that is what the 
    NG is designed around. And there are also events that do additional things: upload files, delete files, compile pdf,
    extract text, qa checks. These need something otherwise the metadata changes will be well handled by the SubmitAPI
    But all the other things, the difficult things, will not be.  
    
    3. Is the NG style Event where the event knows how to change the submission good? Can we expand that to allow the
    event access to the SubmitAPI to do file uploads, file deletes, etc? How would we implement something like "no
    event can succeed before the arXiv TOS has been accepted?" What does the NG design get us and can we get it a different
    way?
    
    4. High on the list of priorities are testability and simplicity. Testability has a lot to do with can we mock 
    things? Can we do pytest fixtures? 
          
    
    """
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
