"""Staging store for SWORD media deposits.

SWORD's media workspace is **user-scoped and exists before any submission does**: a
depositor POSTs files one at a time, gets ``edit-media`` links back, and only later
POSTs a metadata wrapper referencing them. Deposits are retained for at least 30
days and are referenceable across deposits, including replacements
(``submit_sword.md:735-744``).

That does not fit `submit_ce.api.file_store.SubmissionFileStore`, which is
submission-scoped in every method, so deposits live here instead and are copied
into a submission's workspace when a wrapper claims them.

Legacy kept this on local disk under ``/cache/atomdeposits`` (``Config.pm:44``):

    <yymm>/<id>.<ext>     the deposited bytes
    <yymm>/<id>.atom      the response entry, re-served by GET
    <yymm>/<id>.xml       the raw wrapper, for a metadata deposit
    nextid                a counter file mutated under flock

`GsDepositStore` mirrors that layout onto a bucket, with the ``flock`` replaced by
a compare-and-swap on the counter object's generation. `InMemoryDepositStore` is
the same semantics without I/O, for tests.

**Ownership is recorded explicitly** rather than recovered by re-parsing the
sidecar's ``<author><name>`` the way legacy does (``AtomPP.pm:379,1124-1129``).
One authoritative field beats re-deriving it from a document we also generate.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from submit_ce.domain.size_limits import SIZE_LIMIT_POLICY
from submit_ce.sword.errors import SwordFault

COUNTER_OBJECT = "nextid"
"""Name of the allocation counter, as in legacy's ``DEPOSITDIR/nextid``."""

DEPOSIT_ID_PATTERN = re.compile(r"^(\d{4})\d{4,}$")
"""``YYMM`` followed by at least four digits (``AtomPP.pm:367-368``)."""

MAX_ALLOCATION_ATTEMPTS = 10

_SUBTYPE_EXTENSIONS = {"jpeg": "jpg", "postscript": "ps"}
"""``AtomPP.pm:1110-1113``."""

SUPPORTED_MEDIA_TYPES = frozenset({
    "application/zip",
    "application/xml",
    "text/xml",
    "application/pdf",
    "application/postscript",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
})
"""Media types a deposit may carry, from the dispatch table at ``AtomPP.pm:262-274``.

Note what is *absent*: ``application/vnd.openxmlformats-...wordprocessingml.document``.
The service document advertises docx (``ServiceDoc.pm:78``) but there has never
been a handler for it, so a docx deposit gets 415. Reproduced deliberately;
correcting the advertisement is a separate change.
"""

ATOM_ENTRY_TYPE = "application/atom+xml"
"""A wrapper deposit rather than media; stored as ``.xml`` (``AtomPP.pm:623``)."""


def max_deposit_bytes() -> int:
    """Largest deposit accepted, from submit-ce's own size policy.

    50 MiB, up from legacy's ``CGI::POST_MAX`` of 10 MiB (``AtomPP.pm:9``), per the
    plan's decision 5.
    """
    return SIZE_LIMIT_POLICY.total_limit()


def check_deposit_size(data: bytes) -> None:
    """Reject a request body larger than the deposit limit.

    Called from every route that accepts one, not just the media path. Legacy
    capped the whole request regardless of content type -- ``$CGI::POST_MAX``
    (``AtomPP.pm:9``) was checked against ``Content-Length`` before the body was
    read -- so a wrapper was capped as well, and checking only on the way to the
    store would leave Atom documents less constrained here than under the Perl.

    ESIZE rather than EMDTP: see `submit_ce.sword.errors._ADDITIONS`.
    """
    limit = max_deposit_bytes()
    if len(data) > limit:
        raise SwordFault(
            "ESIZE",
            f"deposit of {len(data)} bytes exceeds the {limit} byte limit")


def extension_for(content_type: str) -> str:
    """Filename extension for a deposited media type.

    Legacy expresses this mapping twice -- a content-type dispatch table for
    storing (``AtomPP.pm:262-274``) and a MIME-subtype rule for resolving a
    wrapper's links (``AtomPP.pm:1109-1116``) -- and the two agree on every value,
    so one function serves both. Parameters after ``;`` are ignored.

    Raises `SwordFault` EMDTP (415) for anything unsupported.
    """
    bare = content_type.split(";", 1)[0].strip().lower()
    if bare == ATOM_ENTRY_TYPE:
        return "xml"
    if bare not in SUPPORTED_MEDIA_TYPES:
        raise SwordFault("EMDTP", content_type)
    subtype = bare.split("/", 1)[1] if "/" in bare else bare
    return _SUBTYPE_EXTENSIONS.get(subtype, subtype)


def extension_for_link(mime: str) -> str:
    """Extension a wrapper's ``rel="related"`` link implies.

    Separate entry point because a malformed link type is ELKTP rather than
    EMDTP (``AtomPP.pm:1117-1121``).
    """
    parts = [part for part in re.split(r"[/;]", mime or "") if part]
    if len(parts) < 2:
        raise SwordFault("ELKTP", f"Is this an accepted mime-type: {mime}")
    subtype = parts[1].strip().lower()
    return _SUBTYPE_EXTENSIONS.get(subtype, subtype)


MAX_SEQUENCE = 9999
"""Largest sequence that still yields an eight-digit id.

``replace.DEPOSIT_ATOM`` matches exactly eight digits, so a ninth would make
``PUT /sword-app/edit/<id>.atom`` stop resolving -- silently, since the deposit
itself would still succeed. With a monthly reset this needs 10,000 deposits in one
month to reach; without one it was only a matter of time.
"""

FIRST_SEQUENCE = 1
"""What a new month starts from, matching legacy's ``echo -n 1 > nextid`` cron."""


def as_utc(moment: datetime) -> datetime:
    """``moment`` in UTC, treating a naive datetime as already UTC.

    Naive values are not converted: ``astimezone`` would read them as system local
    time, which is the assumption this whole scheme is trying to get rid of.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def period_of(moment: datetime) -> str:
    """The ``YYMM`` a moment belongs to, in UTC.

    Converted rather than assumed. The period and the id must be decided by the
    same clock: legacy reset the counter from a local-time cron while reading
    ``localtime()`` for the id, and any disagreement between those two reissues ids
    from earlier in the month. A caller passing a non-UTC datetime would reopen
    exactly that gap -- at 01:00 on 1 September in UTC+2 it is still August in UTC,
    and the two would disagree about which month the deposit belongs to.
    """
    utc = as_utc(moment)
    return f"{utc.year % 100:02d}{utc.month:02d}"


def format_deposit_id(counter: int, when: Optional[datetime] = None) -> str:
    """Build a deposit id: ``YYMM`` plus the sequence, zero-padded to four.

    ``AtomPP.pm:599-603``.
    """
    moment = as_utc(when) if when else datetime.now(timezone.utc)
    return f"{period_of(moment)}{counter:04d}"


def yymm_of(deposit_id: str) -> str:
    """The ``YYMM`` shard a deposit id lives under.

    Raises `SwordFault` ENMDI for an id that cannot name a deposit.
    """
    match = DEPOSIT_ID_PATTERN.match(deposit_id)
    if not match:
        raise SwordFault("ENMDI", f"info:arxiv/app/{deposit_id}")
    return match.group(1)


@dataclass(frozen=True)
class StagedDeposit:
    """One deposited media resource awaiting a wrapper."""

    deposit_id: str
    owner: str
    extension: str
    content_type: str
    size: int
    created: datetime

    @property
    def path(self) -> str:
        """Object path within the store."""
        return f"{yymm_of(self.deposit_id)}/{self.deposit_id}.{self.extension}"


class DepositStore(ABC):
    """Allocate deposit ids and hold deposited bytes until a wrapper claims them."""

    # -- counter primitives, implemented per backend -------------------------

    @abstractmethod
    def _read_counter(self) -> Tuple[Optional[str], int, object]:
        """Stored period, sequence, and an opaque version token.

        The period is None when the stored value predates it -- a bare integer
        written by legacy or by an older build. `allocate_id` reads that as "the
        current period", so the sequence carries on rather than restarting and
        reissuing ids that month already used.
        """

    @abstractmethod
    def _write_counter(self, period: str, sequence: int, version: object) -> bool:
        """Store ``period`` and ``sequence`` only if the counter still matches
        ``version``.

        Returns False on a conflicting concurrent write.
        """

    # -- allocation ----------------------------------------------------------

    def allocate_id(self, when: Optional[datetime] = None) -> str:
        """Reserve the next deposit id.

        Reads the counter and writes back one more, retrying on contention. The
        id encodes the value *before* the increment, matching ``AtomPP.pm:588-599``.

        The sequence restarts at 1 when the stored period is not the current one,
        which is what makes ids unique: only ``YYMM`` distinguishes one month's
        deposits from the next. Legacy did this from cron
        (``echo -n 1 > nextid`` on the 1st); doing it here means the same instant
        decides both the period and the id, so there is no window in which the
        counter has rolled over but the id has not.

        Raises `SwordFault` ENAVL (503) when contention cannot be resolved, which
        is what legacy answers when it cannot take the lock
        (``AtomPP.pm:256-260``).
        """
        moment = as_utc(when) if when else datetime.now(timezone.utc)
        period = period_of(moment)

        for _ in range(MAX_ALLOCATION_ATTEMPTS):
            stored_period, sequence, version = self._read_counter()
            if stored_period is not None and stored_period != period:
                sequence = FIRST_SEQUENCE
            if sequence > MAX_SEQUENCE:
                raise SwordFault(
                    "ENAVL",
                    f"deposit sequence for {period} is exhausted at {sequence}")
            if self._write_counter(period, sequence + 1, version):
                return format_deposit_id(sequence, moment)
        raise SwordFault("ENAVL", "could not allocate a deposit identifier")

    # -- storage -------------------------------------------------------------

    @abstractmethod
    def save(self, deposit_id: str, owner: str, content_type: str,
             data: bytes) -> StagedDeposit:
        """Store deposited bytes. Raises EMDTP for an unsupported media type."""

    @abstractmethod
    def get(self, deposit_id: str) -> Optional[StagedDeposit]:
        """Metadata for a deposit, or None."""

    @abstractmethod
    def read(self, deposit_id: str) -> Optional[bytes]:
        """Deposited bytes, or None."""

    @abstractmethod
    def save_entry(self, deposit_id: str, document: bytes,
                   owner: Optional[str] = None) -> None:
        """Store the ``.atom`` response entry for later GET.

        ``owner`` records who may retrieve it. It matters for a **wrapper** deposit,
        which stores an entry without any media under its own id -- so there is no
        `StagedDeposit` to carry the owner, and without this the entry would be
        unreadable by the depositor who created it.
        """

    @abstractmethod
    def read_entry(self, deposit_id: str) -> Optional[bytes]:
        """The stored ``.atom`` entry, or None."""

    @abstractmethod
    def extensions(self, deposit_id: str) -> List[str]:
        """Extensions actually present for an id.

        Lets the wrapper-link resolver distinguish "no such deposit" from "that
        deposit exists but not with the type you claimed", which is the difference
        between the two ENMDI messages at ``AtomPP.pm:1133-1147``.
        """

    # -- shared helpers ------------------------------------------------------

    def check_size(self, data: bytes) -> None:
        """Store-level guard, so nothing oversize is written by any caller.

        The routes call `check_deposit_size` earlier, which is what makes the limit
        apply to wrapper deposits too; this stays as the invariant for anything
        reaching a store directly.
        """
        check_deposit_size(data)

    @abstractmethod
    def owner_of(self, deposit_id: str) -> Optional[str]:
        """Who created this id, whether by depositing media or a wrapper."""

    def owned_by(self, deposit_id: str, owner: str) -> bool:
        """Whether ``owner`` created this id.

        A miss is ENOWN (``AtomPP.pm:384-388``). Comparison is exact: the
        depositor name is a tapir nickname, which is case-sensitive.
        """
        recorded = self.owner_of(deposit_id)
        return recorded is not None and recorded == owner


@dataclass
class InMemoryDepositStore(DepositStore):
    """A `DepositStore` with no I/O, for tests and local runs.

    ``counter_hook`` is called immediately after each counter read; a test can use
    it to interleave a competing write and exercise the compare-and-swap.
    """

    counter: int = 1
    period: Optional[str] = None
    version: int = 0
    deposits: Dict[str, StagedDeposit] = field(default_factory=dict)
    blobs: Dict[str, bytes] = field(default_factory=dict)
    entries: Dict[str, bytes] = field(default_factory=dict)
    owners: Dict[str, str] = field(default_factory=dict)
    counter_hook: Optional[object] = None

    def _read_counter(self) -> Tuple[Optional[str], int, object]:
        value, period, version = self.counter, self.period, self.version
        if self.counter_hook is not None:
            self.counter_hook()
        return period, value, version

    def _write_counter(self, period: str, sequence: int, version: object) -> bool:
        if version != self.version:
            return False
        self.counter = sequence
        self.period = period
        self.version += 1
        return True

    def save(self, deposit_id: str, owner: str, content_type: str,
             data: bytes) -> StagedDeposit:
        extension = extension_for(content_type)
        self.check_size(data)
        deposit = StagedDeposit(
            deposit_id=deposit_id,
            owner=owner,
            extension=extension,
            content_type=content_type,
            size=len(data),
            created=datetime.now(timezone.utc),
        )
        self.deposits[deposit_id] = deposit
        self.blobs[deposit_id] = data
        self.owners[deposit_id] = owner
        return deposit

    def get(self, deposit_id: str) -> Optional[StagedDeposit]:
        return self.deposits.get(deposit_id)

    def read(self, deposit_id: str) -> Optional[bytes]:
        return self.blobs.get(deposit_id)

    def save_entry(self, deposit_id: str, document: bytes,
                   owner: Optional[str] = None) -> None:
        self.entries[deposit_id] = document
        if owner is not None:
            self.owners[deposit_id] = owner

    def read_entry(self, deposit_id: str) -> Optional[bytes]:
        return self.entries.get(deposit_id)

    def owner_of(self, deposit_id: str) -> Optional[str]:
        return self.owners.get(deposit_id)

    def extensions(self, deposit_id: str) -> List[str]:
        deposit = self.deposits.get(deposit_id)
        return [deposit.extension] if deposit else []
