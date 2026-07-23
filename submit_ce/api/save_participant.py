"""Participants enlisted in the ``SubmitApi.save()`` transaction.

``SubmitApi.save()`` implementations run a critical section: load and lock the
submission, validate and execute events, persist them, and commit. A
:class:`SaveParticipant` is an object enlisted in that transaction with
callbacks at defined phases. Unlike a decorator wrapping ``save()`` from the
outside, a participant shares the fate of the transaction: it can veto the
save by raising, and it is notified when the transaction rolls back.

Participants are for infrastructure concerns about the save as a whole
(notification, audit, metrics). Behavior that is semantically part of a
submission's history belongs on the event lifecycle instead
(:meth:`EventWithSideEffect.validate_under_lock`,
:meth:`EventWithSideEffect.execute`, :meth:`Event.get_consequences`).

Participants are injected via the implementation's constructor, not
registered dynamically.

No transaction handle is exposed on :class:`SaveContext`. This is deliberate:
it is deferred until a use case needs it (e.g. an outbox participant that
writes rows in the same transaction). Until then ``before_commit``
participants can observe state and veto by raising, but cannot write in the
same transaction.
"""
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence, TYPE_CHECKING

from submit_ce.domain import Event, Submission

if TYPE_CHECKING:  # avoid circular import with submit_ce.api.submit
    from submit_ce.api import SubmitApi


class SavePhase(str, Enum):
    """Where the save critical section is (or was, when it failed).

    The save loop updates :attr:`SaveContext.phase` just before each risky
    step, so a :class:`SaveFailure` can report exactly where an exception
    escaped without participants reverse-engineering it from exception types.
    """

    LOAD_LOCK = "load_lock"
    """Loading the submission with the row lock."""

    PARTICIPANT_UNDER_LOCK = "participant_under_lock"
    """A participant's :meth:`SaveParticipant.under_lock` is running."""

    EVENT_CONSEQUENCES = "event_consequences"
    """A runtime check that the Event only emits consequences of the type defined in the class."""

    EVENT_VALIDATE_UNDER_LOCK = "event_validate_under_lock"
    """An event's ``validate_under_lock()`` is running."""

    EVENT_EXECUTE = "event_execute"
    """An event's ``execute()`` (side effects) is running. Side effects are
    NOT rolled back by the database; a failure here leaves that event's side
    effects in an unknown partial state."""

    EVENT_APPLY = "event_apply"
    """An event's pure state projection is running."""

    EVENT_PERSIST = "event_persist"
    """The event is being written to the database."""

    PARTICIPANT_BEFORE_COMMIT = "participant_before_commit"
    """A participant's :meth:`SaveParticipant.before_commit` is running."""

    COMMIT = "commit"
    """``session.commit()`` itself. A failure here means the database state
    is indeterminate (the commit may or may not have taken effect) —
    participants should alert, not compensate."""


@dataclass
class SaveContext:
    """State of one ``save()`` transaction, passed to every participant phase.

    Fields are populated as the save proceeds; a participant sees the fields
    that exist at its phase (e.g. ``after`` and ``committed`` are populated by
    ``before_commit`` time). The cursor fields (``phase``, ``current_event``,
    ``current_participant``) track where the save loop is and feed
    :class:`SaveFailure` on rollback.
    """

    api: "SubmitApi"
    submission_id: Optional[str]
    requested_events: Sequence[Event]
    """The events as passed by the caller, before consequences."""

    before: Optional[Submission] = None
    """Submission state as loaded under the lock. None when creating."""

    existing_events: List[Event] = field(default_factory=list)
    after: Optional[Submission] = None
    """Projected submission state after the events applied so far."""

    committed: List[Event] = field(default_factory=list)
    """Events persisted this save, including consequence events."""

    # cursor — updated by the save loop just before each risky call
    phase: SavePhase = SavePhase.LOAD_LOCK
    current_event: Optional[Event] = None
    current_participant: Optional["SaveParticipant"] = None


@dataclass(frozen=True)
class SaveFailure:
    """Why and where a save transaction rolled back.

    Passed to :meth:`SaveParticipant.on_rollback`. ``phase`` says where the
    exception escaped; the context (``ctx.committed``, each event's
    ``executed`` timestamp) says what had already happened. Both are needed:
    alerting keys off ``phase``, cleanup keys off what executed. An event with
    ``executed`` set definitely ran its side effects (which survive the DB
    rollback); ``phase == EVENT_EXECUTE`` means ``event``'s side effects are
    in an unknown partial state.
    """

    exc: BaseException
    phase: SavePhase
    event: Optional[Event] = None
    """The event being processed when the exception escaped, if any."""

    participant: Optional["SaveParticipant"] = None
    """The participant that raised, if one did."""


class SaveParticipant(ABC):
    """A participant enlisted in the ``save()`` transaction.

    All methods default to no-ops; override only the phases you care about.

    Ordering: implementations call ``under_lock`` in participant list order
    and ``before_commit``, ``after_commit`` and ``on_rollback`` in reverse
    list order (onion semantics).
    """

    def under_lock(self, ctx: SaveContext) -> None:
        """Called inside the transaction, after the submission row is loaded
        and locked, before any event validates or executes.

        When the save creates a new submission there is no row to lock and
        ``ctx.before`` is None.

        Raising here is the clean abort: nothing has executed or persisted,
        the rollback is complete, and the exception propagates to the caller.
        """

    def before_commit(self, ctx: SaveContext) -> None:
        """Called inside the transaction after all events (including
        consequences) have been applied and persisted, just before commit.

        ``ctx.after`` and ``ctx.committed`` are populated. Raising rolls the
        database transaction back — with the same caveat as
        ``validate_under_lock``: already-executed event side effects are not
        rolled back.
        """

    def after_commit(self, ctx: SaveContext) -> None:
        """Called after the transaction committed successfully.

        The save has succeeded and the caller will be told so: exceptions
        raised here are logged and swallowed, never propagated.
        """

    def on_rollback(self, ctx: SaveContext, failure: SaveFailure) -> None:
        """Called after the transaction rolled back.

        Fires only on an actual rollback — not for ``after_commit`` failures.
        Exceptions raised here are logged and never mask the original
        exception, which propagates to the caller unchanged.
        """
