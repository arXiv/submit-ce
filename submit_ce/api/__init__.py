"""Core persistence methods for submissions and submission events."""

from abc import ABC, abstractmethod
from io import BytesIO
from typing import Tuple, List, Optional, Sequence, Protocol

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
            # if len(events) == 0:
            #     raise NothingToDo('Must pass at least one event')
            # events_list = list(events)   # Coerce to list so that we can index.
            # prior: List[Event] = []
            # before: Optional[Submission] = None
            #
            # # We need ACIDity surrounding the the validation and persistence of new
            # # events.
            # with classic.transaction():
            #     # Get the current state of the submission from past events. Normally we
            #     # would not want to load all past events, but legacy components may be
            #     # active, and the legacy projected state does not capture all of the
            #     # detail in the event model.
            #     if submission_id is not None:
            #         # This will create a shared lock on the submission rows while we
            #         # are working with them.
            #         before, prior = classic.get_submission(submission_id,
            #                                                for_update=True)
            #
            #     # Either we need a submission ID, or the first event must be a
            #     # creation.
            #     elif events_list[0].submission_id is None \
            #             and not isinstance(events_list[0], CreateSubmission):
            #         raise NoSuchSubmission('Unable to determine submission')
            #
            #     committed: List[Event] = []
            #     for event in events_list:
            #         # Fill in submission IDs, if they are missing.
            #         if event.submission_id is None and submission_id is not None:
            #             event.submission_id = submission_id
            #
            #         # The created timestamp should be roughly when the event was
            #         # committed. Since the event projection may refer to its own ID
            #         # (which is based) on the creation time, this must be set before
            #         # the event is applied.
            #         event.created = datetime.now(UTC)
            #         # Mutation happens here; raises InvalidEvent.
            #         logger.debug('Apply event %s: %s', event.event_id, event.NAME)
            #         after = event.apply(before)
            #         committed.append(event)
            #         if not event.committed:
            #             after, consequent_events = event.commit(_store_event)
            #             committed += consequent_events
            #
            #         before = after      # Prepare for the next event.
            #
            #     all_ = sorted(set(prior) | set(committed), key=lambda e: e.created)
            #     return after, list(all_)
            #

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