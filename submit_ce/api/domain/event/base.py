"""Provides the base event class."""

import copy
import hashlib
from datetime import datetime
from typing import Optional, Callable, Tuple, Iterable, List, ClassVar, \
    Type, Any

from pydantic import BaseModel

from ..agent import Agent
from ..submission import Submission

Events = Iterable['Event']
Condition = Callable[['Event', Optional[Submission], Submission], bool]
Callback = Callable[['Event', Optional[Submission], Submission], Events]
Decorator = Callable[[Callable], Callable]
Rule = Tuple[Condition, Callback]
Store = Callable[['Event', Optional[Submission], Submission],
                 Tuple['Event', Submission]]


class Event(BaseModel):
    """
    Base class for submission-related events/commands.

    An event represents a change to a :class:`.domain.submission.Submission`.
    Rather than changing submissions directly, an application should create
    (and store) events. Each event class must inherit from this base class,
    extend it with whatever data is needed for the event, and define methods
    for validation and projection (changing a submission):

    - ``validate(self, submission: Submission) -> None`` should raise
      :class:`.InvalidEvent` if the event instance has invalid data.
    - ``project(self, submission: Submission) -> Submission`` should perform
      changes to the :class:`.domain.submission.Submission` and return it.

    An event class also provides a hook for doing things automatically when the
    submission changes. To register a function that gets called when an event
    is committed, use the :func:`bind` method.
    """

    NAME: ClassVar[str] = 'base event'
    NAMED: ClassVar[str] = 'base event'

    creator: Agent
    """
    The agent responsible for the operation represented by this event.

    This is **not** necessarily the creator of the submission.
    """

    created: Optional[datetime] = None   # get_tzaware_utc_now
    """The timestamp when the event was originally committed."""

    proxy: Optional[Agent] = None
    """
    The agent who facilitated the operation on behalf of the :attr:`.creator`.

    This may be an API client, or another user who has been designated as a
    proxy. Note that proxy implies that the creator was not directly involved.
    """

    client: Optional[Agent] = None
    """
    The client through which the :attr:`.creator` performed the operation.

    If the creator was directly involved in the operation, this property should
    be the client that facilitated the operation.
    """

    submission_id: Optional[int] = None
    """
    The primary identifier of the submission being operated upon.

    This is defined as optional to support creation events, and to facilitate
    chaining of events with creation events in the same transaction.
    """

    committed: bool = False
    """
    Indicates whether the event has been committed to the database.

    This should generally not be set from outside this package.
    """

    before: Optional[Submission] = None
    """The state of the submission prior to the event."""

    after: Optional[Submission] = None
    """The state of the submission after the event."""


    @property
    def event_type(self) -> str:
        return self.__class__.__name__

    @classmethod
    def get_event_type(cls) -> str:
        """Get the name of the event type."""
        return cls.__name__

    @property
    def event_id(self) -> str:
        """Unique ID for this event."""
        if not self.created:
            raise RuntimeError('Event not yet committed')
        return self.get_id(self.created, self.event_type, self.creator)

    @staticmethod
    def get_id(created: datetime, event_type: str, creator: Agent) -> str:
        h = hashlib.new('sha1')
        h.update(b'%s:%s:%s' % (created.isoformat().encode('utf-8'),
                                event_type.encode('utf-8'),
                                creator.agent_identifier.encode('utf-8')))
        return h.hexdigest()

    def apply(self, submission: Optional[Submission] = None, ) -> Submission:
        """Apply the projection for this :class:`.Event` instance."""
        self.before = copy.deepcopy(submission)
        # See comment on CreateSubmission, below.
        self.validate(submission)    # type: ignore
        if submission is not None:
            self.after = self.project(copy.deepcopy(submission))
        else:   # See comment on CreateSubmission, below.
            self.after = self.project(None)    # type: ignore
        assert self.after is not None

        self.after.updated = self.created

        # Make sure that the submission has its own ID, if we know what it is.
        if self.after.submission_id is None and self.submission_id is not None:
            self.after.submission_id = self.submission_id
        if self.submission_id is None and self.after.submission_id is not None:
            self.submission_id = self.after.submission_id
        return self.after


    def validate(self, submission: Submission) -> None:
        """Validate this event and its data against a submission."""
        raise NotImplementedError('Must be implemented by subclass')

    def project(self, submission: Submission) -> Submission:
        """Apply this event and its data to a submission.

        This is how the `Event` changes the `submission`."""
        raise NotImplementedError('Must be implemented by subclass')


def _get_subclasses(klass: Type[Event]) -> List[Type[Event]]:
    _subclasses = klass.__subclasses__()
    if _subclasses:
        return _subclasses + [sub for klass in _subclasses
                              for sub in _get_subclasses(klass)]
    return _subclasses


def event_factory(event_type: str, created: datetime, **data: Any) -> Event:
    """
    Generate an :class:`Event` instance from raw :const:`EventData`.

    Parameters
    ----------
    created: datetime,
        Time event was created. Should have TZ.
    event_type : str
        Should be the name of a :class:`.Event` subclass.
    data : kwargs
        Keyword parameters passed to the event constructor.

    Returns
    -------
    :class:`.Event`
        An instance of an :class:`.Event` subclass.

    """
    etypes = {klas.get_event_type(): klas for klas in _get_subclasses(Event)}
    data['created'] = created
    if event_type in etypes:
        # Mypy gives a spurious 'Too many arguments for "Event"'.
        return etypes[event_type](**data)    # type: ignore
    raise RuntimeError('Unknown event type: %s' % event_type)


class EventWithSideEffect(Event):

    executed: Optional[datetime] = None  # timezone aware utc
    """Should only be set when `execute` is called."""

    def pre_execute_validation(self, api: 'SubmitApi', submission: Submission) -> None:
        """Check if is acceptable for `execute` to be called."""

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """
        An :class:`.Event` that has side effects executed through use of the :class:`submit_ce.api.submit.SubmitApi`.

        This should execute without raising an exception. Any problems should be recorded by altering `self`.

        Data about the execution may be recorded by alternating `self.

        This MUST not alter the `submission` since that won't be recorded anywhere. To alter the
        `submission`, do the execute, alter `self` then during `project()` use the data on `self`
        to set the data on the returned `submission`.

        Parameters
        ----------
        api: SubmitApi
            API for use to perform the operation.
        submission: Submission
            The submission related to this :class:`.Event`.

        Returns
        -------
        `None`
            Returns nothing since it operates by side effect. It may alter the :class:`.EventWithSideEffect` to
            record details of the side effect.
        """
        raise NotImplementedError('Must be implemented by subclass')