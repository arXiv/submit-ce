"""Provides the base event class."""
from __future__ import annotations
import copy
import functools
import hashlib
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Callable, Tuple, Iterable, List, ClassVar, \
    Type, Any

from pydantic import BaseModel, RootModel

if TYPE_CHECKING:
    from submit_ce.api.submit import SubmitApi

from ..agent import User, Client
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

    CONSEQUENCE_TYPES: ClassVar[frozenset] = frozenset()
    """Event types this event may emit from :meth:`consequences`.

    Declared statically so the consequence graph over event types can be
    checked for cycles. Empty means this event has no consequences.
    """

    creator: User
    """
    The agent responsible for the operation represented by this event.

    This is **not** necessarily the creator of the submission.
    """

    created: Optional[datetime] = None   # get_tzaware_utc_now
    """The timestamp when the event was originally committed."""

    proxy: Optional[User] = None
    """
    The agent who facilitated the operation on behalf of the :attr:`.creator`.

    This may be an API client, or another user who has been designated as a
    proxy. Note that proxy implies that the creator was not directly involved.
    """

    client: Optional[Client] = None
    """
    The client through which the :attr:`.creator` performed the operation.

    If the creator was directly involved in the operation, this property should
    be the client that facilitated the operation.
    """

    submission_id: Optional[str] = None
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

    _before: Optional[Submission] = None
    """The state of the submission prior to the event. For debugging only."""

    _after: Optional[Submission] = None
    """The state of the submission after the event. For debugging only."""


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
    def get_id(created: datetime, event_type: str, creator: User) -> str:
        h = hashlib.new('sha1')
        h.update(b'%s:%s:%s' % (created.isoformat().encode('utf-8'),
                                event_type.encode('utf-8'),
                                creator.identifier.encode('utf-8')))
        return h.hexdigest()

    def apply(self, submission: Optional[Submission] = None, ) -> Submission:
        """Apply the projection for this :class:`.Event` instance."""
        self._before = copy.deepcopy(submission)
        # See comment on CreateSubmission, below.
        self.validate(submission)    # type: ignore
        if submission is not None:
            self._after = self.project(copy.deepcopy(submission))
        else:   # See comment on CreateSubmission, below.
            self._after = self.project(None)    # type: ignore
        assert self._after is not None

        self._after.updated = self.created

        # Make sure that the submission has its own ID, if we know what it is.
        if self._after.submission_id is None and self.submission_id is not None:
            self._after.submission_id = self.submission_id
        if self.submission_id is None and self._after.submission_id is not None:
            self.submission_id = self._after.submission_id
        return self._after


    def validate(self, submission: Submission) -> None:
        """Validate this event and its data against a submission."""
        raise NotImplementedError('Must be implemented by subclass')

    def project(self, submission: Submission) -> Submission:
        """Apply this event and its data to a submission.

        This is how the `Event` changes the `submission`."""
        raise NotImplementedError('Must be implemented by subclass')

    def consequences(self, submission: Submission) -> List['Event']:
        """Follow-on events implied by this event given the resulting state.

        Called by the `SubmitApi.save()` loop with the submission state *after*
        this event's projection. The types of the returned instances must be a
        subset of :attr:`CONSEQUENCE_TYPES`. This is enforced at runtime in the
        `save()`. Default: no consequences.

        This is intended to be explicit and traceable: an event names the events
        it may spawn, and those types form a directed graph that is checked for
        cycles by a test, so consequence chains are guaranteed to terminate.
        """
        return []

    def get_consequences(self, submission: Submission) -> List['Event']:
        """Return :meth:`consequences`, enforcing the :attr:`CONSEQUENCE_TYPES` contract.

        Raises if an event emits a consequence type it did not declare; this
        keeps the static consequence graph honest at runtime.
        """
        events = self.consequences(submission)
        for event in events:
            if type(event) not in self.CONSEQUENCE_TYPES:
                raise RuntimeError(
                    f"{self.event_type} emitted undeclared consequence "
                    f"{type(event).__name__}; add it to CONSEQUENCE_TYPES")
        return events


@functools.cache
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
    """Events that get the `SubmitApi` to allow side effects. Ex. with the `FileStore`.

    These cannot be serialized to JSON."""
    executed: Optional[datetime] = None  # timezone aware utc
    """Should only be set when `execute` is called."""

    def pre_execute_validation(self, api: SubmitApi, submission: Submission) -> None:
        """Check if is acceptable for `execute` to be called."""
        pass

    def execute(self, api: SubmitApi, submission: Submission) -> None:
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
        pass


class EventList(RootModel):
    """Class for a list of Events."""
    root: list[Event]

    def __iter__(self):
        return iter(self.root)

    def __getitem__(self, item):
        return self.root[item]
