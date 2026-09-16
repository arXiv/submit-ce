"""Deposit id allocation, media-type mapping, and the staging store.

The allocation contract is legacy's: read the counter, hand out the value seen,
write back one more, under a lock (``AtomPP.pm:582-604``). Here the lock is a
compare-and-swap, so the interesting cases are contention and exhaustion.
"""

from datetime import datetime, timezone

import pytest

from submit_ce.sword import deposits
from submit_ce.sword.deposits import (
    InMemoryDepositStore,
    format_deposit_id,
    extension_for,
    extension_for_link,
    max_deposit_bytes,
    yymm_of,
)
from submit_ce.sword.errors import SwordFault

MARCH_2010 = datetime(2010, 3, 17, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------- id formatting


def test_deposit_id_encodes_year_month_and_counter():
    """The manual's tracking example is /resolve/app/10030146."""
    assert format_deposit_id(146, MARCH_2010) == "10030146"


def test_counter_is_zero_padded_to_four():
    assert format_deposit_id(1, MARCH_2010) == "10030001"
    assert format_deposit_id(9999, MARCH_2010) == "10039999"


def test_id_grows_past_eight_digits_when_the_counter_overflows():
    """The counter is global, not per-month (AtomPP.pm:599)."""
    assert format_deposit_id(10000, MARCH_2010) == "100310000"
    assert len(format_deposit_id(10000, MARCH_2010)) == 9


def test_single_digit_month_is_padded():
    assert format_deposit_id(7, datetime(2026, 1, 5, tzinfo=timezone.utc)) == \
        "26010007"


def test_yymm_of_takes_the_first_four_digits():
    assert yymm_of("10030146") == "1003"
    assert yymm_of("100310000") == "1003"


@pytest.mark.parametrize("bad", ["", "abc", "123", "1003abcd", "10a30146"])
def test_yymm_of_rejects_ids_that_cannot_name_a_deposit(bad):
    with pytest.raises(SwordFault) as excinfo:
        yymm_of(bad)
    assert excinfo.value.error.mnemonic == "ENMDI"


# ---------------------------------------------------------- media type mapping


@pytest.mark.parametrize("content_type,extension", [
    ("application/zip", "zip"),
    ("application/pdf", "pdf"),
    ("application/xml", "xml"),
    ("text/xml", "xml"),
    ("image/png", "png"),
    ("image/gif", "gif"),
    ("image/jpg", "jpg"),
    ("image/jpeg", "jpg"),              # AtomPP.pm:1111
    ("application/postscript", "ps"),   # AtomPP.pm:1112
])
def test_extension_for_supported_types(content_type, extension):
    assert extension_for(content_type) == extension


def test_extension_ignores_content_type_parameters():
    assert extension_for("application/zip; charset=binary") == "zip"


def test_atom_entry_is_stored_as_xml():
    """A wrapper deposit is written to <id>.xml (AtomPP.pm:623)."""
    assert extension_for("application/atom+xml") == "xml"
    assert extension_for("application/atom+xml;type=entry") == "xml"


def test_docx_is_rejected_even_though_the_service_document_advertises_it():
    """No handler for it in the dispatch table (AtomPP.pm:262-274)."""
    docx = ("application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document")
    with pytest.raises(SwordFault) as excinfo:
        extension_for(docx)
    assert excinfo.value.error.mnemonic == "EMDTP"
    assert excinfo.value.status == 415


@pytest.mark.parametrize("content_type", [
    "application/octet-stream", "text/plain", "application/dcsip", "",
])
def test_unsupported_media_types_are_415(content_type):
    with pytest.raises(SwordFault) as excinfo:
        extension_for(content_type)
    assert excinfo.value.status == 415


def test_dcsip_is_not_supported():
    """The Data Conservancy path is dead (plan decision 2)."""
    assert "application/dcsip" not in deposits.SUPPORTED_MEDIA_TYPES


# -------------------------------------------------------- link type resolution


@pytest.mark.parametrize("mime,extension", [
    ("application/zip", "zip"),
    ("application/pdf", "pdf"),
    ("image/jpeg", "jpg"),
    ("application/postscript", "ps"),
])
def test_extension_for_link(mime, extension):
    assert extension_for_link(mime) == extension


@pytest.mark.parametrize("mime", ["", "zip", "application", None])
def test_unparseable_link_type_is_elktp(mime):
    """A link whose type has no subtype is ELKTP, not EMDTP (AtomPP.pm:1117)."""
    with pytest.raises(SwordFault) as excinfo:
        extension_for_link(mime)
    assert excinfo.value.error.mnemonic == "ELKTP"


# ---------------------------------------------------------------- allocation


def test_allocate_returns_the_value_before_the_increment():
    store = InMemoryDepositStore(counter=146)
    assert store.allocate_id(MARCH_2010) == "10030146"
    assert store.counter == 147


def test_consecutive_allocations_are_distinct():
    store = InMemoryDepositStore(counter=1)
    ids = [store.allocate_id(MARCH_2010) for _ in range(5)]
    assert ids == ["10030001", "10030002", "10030003", "10030004", "10030005"]
    assert len(set(ids)) == 5


def test_allocation_retries_when_the_counter_moves_underneath_it():
    """A competing writer between read and write must not cause a duplicate id."""
    store = InMemoryDepositStore(counter=10)
    interference = {"count": 0}

    def compete():
        # Once only: simulate another process allocating first.
        if interference["count"] == 0:
            interference["count"] += 1
            store.counter += 1
            store.version += 1

    store.counter_hook = compete
    allocated = store.allocate_id(MARCH_2010)

    # The first attempt saw 10 but lost the race; the retry saw 11.
    assert allocated == "10030011"
    assert interference["count"] == 1


def test_allocation_gives_up_with_enavl_under_permanent_contention():
    """Legacy answers 503 ENAVL when it cannot take the lock (AtomPP.pm:256-260)."""
    store = InMemoryDepositStore(counter=1)
    store.counter_hook = lambda: setattr(store, "version", store.version + 1)

    with pytest.raises(SwordFault) as excinfo:
        store.allocate_id(MARCH_2010)
    assert excinfo.value.error.mnemonic == "ENAVL"
    assert excinfo.value.status == 503


def test_allocation_attempts_are_bounded():
    calls = {"count": 0}
    store = InMemoryDepositStore(counter=1)

    def bump():
        calls["count"] += 1
        store.version += 1

    store.counter_hook = bump
    with pytest.raises(SwordFault):
        store.allocate_id(MARCH_2010)
    assert calls["count"] == deposits.MAX_ALLOCATION_ATTEMPTS


# --------------------------------------------------------------------- storage


@pytest.fixture
def store():
    return InMemoryDepositStore(counter=1)


def test_save_and_read_round_trip(store):
    payload = b"PK\x03\x04zip"
    deposit_id = store.allocate_id(MARCH_2010)
    deposit = store.save(deposit_id, "vtex", "application/zip", payload)

    assert deposit.deposit_id == deposit_id
    assert deposit.owner == "vtex"
    assert deposit.extension == "zip"
    assert deposit.size == len(payload)
    assert store.read(deposit_id) == payload


def test_deposit_path_shape(store):
    deposit = store.save("10030146", "vtex", "application/pdf", b"%PDF")
    assert deposit.path == "1003/10030146.pdf"


def test_get_returns_none_for_an_unknown_id(store):
    assert store.get("10039999") is None
    assert store.read("10039999") is None


def test_atom_sidecar_round_trip(store):
    store.save("10030146", "vtex", "application/zip", b"x")
    store.save_entry("10030146", b"<entry/>")
    assert store.read_entry("10030146") == b"<entry/>"


def test_read_entry_is_none_when_absent(store):
    assert store.read_entry("10030146") is None


def test_extensions_lists_what_is_present(store):
    store.save("10030146", "vtex", "application/pdf", b"%PDF")
    assert store.extensions("10030146") == ["pdf"]
    assert store.extensions("10039999") == []


# ------------------------------------------------------------------- ownership


def test_ownership_is_recorded_and_checked(store):
    store.save("10030146", "vtex", "application/zip", b"x")
    assert store.owned_by("10030146", "vtex")
    assert not store.owned_by("10030146", "someone-else")


def test_ownership_comparison_is_case_sensitive(store):
    """The owner is a tapir nickname, which is case-sensitive."""
    store.save("10030146", "vtex", "application/zip", b"x")
    assert not store.owned_by("10030146", "VTEX")


def test_unknown_deposit_is_owned_by_nobody(store):
    assert not store.owned_by("10039999", "vtex")


# ------------------------------------------------------------------ size limit


def test_max_deposit_is_the_50mb_policy_limit():
    """Raised from legacy's 10 MiB CGI::POST_MAX (decision 5)."""
    assert max_deposit_bytes() == 50 * 1024 * 1024


def test_oversize_deposit_is_refused(store):
    oversize = b"x" * (max_deposit_bytes() + 1)
    with pytest.raises(SwordFault) as excinfo:
        store.save("10030146", "vtex", "application/zip", oversize)
    assert excinfo.value.error.mnemonic == "ESIZE"
    assert excinfo.value.status == 413


def test_a_deposit_at_exactly_the_limit_is_accepted(store):
    at_limit = b"x" * max_deposit_bytes()
    deposit = store.save("10030146", "vtex", "application/zip", at_limit)
    assert deposit.size == max_deposit_bytes()


# ------------------------------------------------------- the monthly reset


def _at(year, month, day=1):
    from datetime import datetime, timezone
    return datetime(year, month, day, tzinfo=timezone.utc)


def test_the_sequence_restarts_in_a_new_month(store):
    """Only YYMM separates one month's ids from the next, so it has to restart."""
    assert store.allocate_id(_at(2026, 8)) == "26080001"
    assert store.allocate_id(_at(2026, 8)) == "26080002"
    assert store.allocate_id(_at(2026, 9)) == "26090001"


def test_the_reset_needs_no_cron(store):
    """Legacy ran `echo -n 1 > nextid` on the 1st.

    Deciding it here means one clock fixes both the period and the id, closing the
    window where the counter had rolled over and the id had not -- which reissued
    ids from earlier in the month.
    """
    store.allocate_id(_at(2026, 8, 31))
    assert store.allocate_id(_at(2026, 9, 1)) == "26090001"


def test_ids_stay_unique_across_a_month_boundary(store):
    """The property the whole scheme exists for."""
    issued = [store.allocate_id(_at(2026, 8, 30)) for _ in range(5)]
    issued += [store.allocate_id(_at(2026, 9, 1)) for _ in range(5)]
    assert len(set(issued)) == len(issued)


def test_a_legacy_counter_carries_on_rather_than_restarting(store):
    """A bare integer has no period; restarting would reissue live ids."""
    store.counter, store.period = 146, None
    assert store.allocate_id(_at(2026, 8)) == "26080146"
    assert store.allocate_id(_at(2026, 8)) == "26080147"


def test_an_exhausted_sequence_is_refused(store):
    """A ninth digit would silently break replacement resolution.

    `replace.DEPOSIT_ATOM` matches exactly eight digits, so the deposit would
    succeed and only the later PUT would fail -- better to stop here.
    """
    store.counter, store.period = 10000, "2608"
    with pytest.raises(SwordFault) as excinfo:
        store.allocate_id(_at(2026, 8))
    assert excinfo.value.error.mnemonic == "ENAVL"
    assert "exhausted" in excinfo.value.summary


def test_the_last_usable_sequence_still_works(store):
    """Off-by-one on the boundary: 9999 is the last eight-digit id."""
    store.counter, store.period = 9999, "2608"
    assert store.allocate_id(_at(2026, 8)) == "26089999"


def test_period_of_is_utc(store):
    """A local-time period against a UTC id is what created the old race."""
    from datetime import datetime, timedelta, timezone

    from submit_ce.sword.deposits import period_of
    # 31 Aug 23:00 UTC is already September in UTC+2.
    late_august = datetime(2026, 8, 31, 23, 0, tzinfo=timezone.utc)
    assert period_of(late_august) == "2608"
    assert period_of(late_august.astimezone(timezone(timedelta(hours=2)))) == "2608"


def test_a_naive_datetime_is_taken_as_utc(store):
    """Not converted: astimezone would read it as system local time."""
    from datetime import datetime

    from submit_ce.sword.deposits import period_of
    assert period_of(datetime(2026, 8, 31, 23, 0)) == "2608"
