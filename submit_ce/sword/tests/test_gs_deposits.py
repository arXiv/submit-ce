"""`GsDepositStore` against a fake bucket.

The point is the conditional write: legacy held an exclusive ``flock`` on the
counter file (``AtomPP.pm:586-596``), and the replacement is
``if_generation_match``, with GCS answering 412 when another writer won. The fake
below implements just enough of the ``storage`` API to exercise that, including
generation bookkeeping -- no network, which the suite's socket guard would block
anyway.
"""

from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import PreconditionFailed

from submit_ce.sword.errors import SwordFault
from submit_ce.sword.gs_deposits import OWNER_METADATA_KEY, GsDepositStore

MARCH_2010 = datetime(2010, 3, 17, 12, 0, tzinfo=timezone.utc)


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket = bucket
        self.name = name
        self.metadata = None
        self.content_type = None
        self.time_created = None

    # -- the bits of the real API this store uses ---------------------------

    @property
    def generation(self):
        return self.bucket.generations.get(self.name, 0)

    @property
    def size(self):
        data = self.bucket.objects.get(self.name)
        return len(data) if data is not None else 0

    def download_as_bytes(self):
        return self.bucket.objects[self.name]

    def upload_from_string(self, data, content_type=None,
                           if_generation_match=None):
        if isinstance(data, str):
            data = data.encode()
        if if_generation_match is not None:
            current = self.bucket.generations.get(self.name, 0)
            if current != if_generation_match:
                raise PreconditionFailed(
                    f"generation mismatch: {current} != {if_generation_match}")
        self.bucket.objects[self.name] = data
        self.bucket.generations[self.name] = \
            self.bucket.generations.get(self.name, 0) + 1
        self.content_type = content_type
        self.time_created = MARCH_2010
        self.bucket.blobs[self.name] = self


class FakeBucket:
    def __init__(self):
        self.objects = {}
        self.generations = {}
        self.blobs = {}

    def blob(self, name):
        return self.blobs.get(name) or FakeBlob(self, name)

    def get_blob(self, name):
        """None when absent, like the real client."""
        return self.blobs.get(name) if name in self.objects else None


class FakeClient:
    def __init__(self, bucket=None):
        self._bucket = bucket or FakeBucket()

    def bucket(self, _name):
        return self._bucket

    def list_blobs(self, bucket, prefix=""):
        return [blob for name, blob in sorted(bucket.blobs.items())
                if name.startswith(prefix)]


@pytest.fixture
def bucket():
    return FakeBucket()


@pytest.fixture
def store(bucket):
    return GsDepositStore(gs_bucket="arxiv-submit-dev",
                          gs_prefix="sword-deposits",
                          client=FakeClient(bucket))


# ------------------------------------------------------------------- allocation


def test_first_allocation_creates_the_counter(store, bucket):
    assert store.allocate_id(MARCH_2010) == "10030001"
    assert bucket.objects["sword-deposits/nextid"] == b"2"


def test_counter_is_created_with_a_must_not_exist_precondition(store, bucket):
    """A generation of 0 is GCS's "object must not exist"."""
    store.allocate_id(MARCH_2010)
    assert bucket.generations["sword-deposits/nextid"] == 1


def test_successive_allocations_advance(store):
    ids = [store.allocate_id(MARCH_2010) for _ in range(3)]
    assert ids == ["10030001", "10030002", "10030003"]


def test_allocation_reads_an_existing_counter(store, bucket):
    bucket.objects["sword-deposits/nextid"] = b"146"
    bucket.generations["sword-deposits/nextid"] = 7
    bucket.blobs["sword-deposits/nextid"] = FakeBlob(bucket, "sword-deposits/nextid")

    assert store.allocate_id(MARCH_2010) == "10030146"
    assert bucket.objects["sword-deposits/nextid"] == b"147"


def test_counter_whitespace_is_tolerated(store, bucket):
    """Legacy chomps the line it reads (AtomPP.pm:597)."""
    bucket.objects["sword-deposits/nextid"] = b"42\n"
    bucket.generations["sword-deposits/nextid"] = 1
    bucket.blobs["sword-deposits/nextid"] = FakeBlob(bucket, "sword-deposits/nextid")

    assert store.allocate_id(MARCH_2010) == "10030042"


def test_a_conflicting_write_is_retried(store, bucket):
    """Another depositor allocates between our read and our write."""
    store.allocate_id(MARCH_2010)  # counter now 2, generation 1

    original = FakeBlob.upload_from_string
    state = {"interfered": False}

    def interfering_upload(self, data, content_type=None,
                           if_generation_match=None):
        if (not state["interfered"]
                and self.name.endswith("nextid")
                and if_generation_match is not None):
            state["interfered"] = True
            # Someone else bumps the generation first.
            bucket.generations[self.name] += 1
            bucket.objects[self.name] = b"99"
        return original(self, data, content_type=content_type,
                        if_generation_match=if_generation_match)

    FakeBlob.upload_from_string = interfering_upload
    try:
        allocated = store.allocate_id(MARCH_2010)
    finally:
        FakeBlob.upload_from_string = original

    assert state["interfered"]
    # The retry must have re-read the counter, not reused the stale value.
    assert allocated == "10030099"


def test_permanent_contention_raises_enavl(store, bucket):
    original = FakeBlob.upload_from_string

    def always_conflict(self, data, content_type=None, if_generation_match=None):
        if if_generation_match is not None:
            raise PreconditionFailed("always")
        return original(self, data, content_type=content_type)

    FakeBlob.upload_from_string = always_conflict
    try:
        with pytest.raises(SwordFault) as excinfo:
            store.allocate_id(MARCH_2010)
    finally:
        FakeBlob.upload_from_string = original

    assert excinfo.value.error.mnemonic == "ENAVL"
    assert excinfo.value.status == 503


def test_a_corrupt_counter_raises(store, bucket):
    bucket.objects["sword-deposits/nextid"] = b"not a number"
    bucket.generations["sword-deposits/nextid"] = 1
    bucket.blobs["sword-deposits/nextid"] = FakeBlob(bucket, "sword-deposits/nextid")

    with pytest.raises(ValueError):
        store.allocate_id(MARCH_2010)


# --------------------------------------------------------------------- storage


def test_media_is_stored_under_the_yymm_shard(store, bucket):
    store.save("10030146", "vtex", "application/zip", b"PK\x03\x04")
    assert "sword-deposits/1003/10030146.zip" in bucket.objects


def test_owner_is_kept_in_object_metadata(store, bucket):
    store.save("10030146", "vtex", "application/pdf", b"%PDF")
    blob = bucket.blobs["sword-deposits/1003/10030146.pdf"]
    assert blob.metadata == {OWNER_METADATA_KEY: "vtex"}


def test_round_trip_read(store):
    store.save("10030146", "vtex", "application/zip", b"payload")
    assert store.read("10030146") == b"payload"


def test_get_reports_the_recorded_owner_and_extension(store):
    store.save("10030146", "vtex", "application/pdf", b"%PDF")
    deposit = store.get("10030146")
    assert deposit.owner == "vtex"
    assert deposit.extension == "pdf"
    assert deposit.size == 4


def test_get_is_none_when_absent(store):
    assert store.get("10039999") is None
    assert store.read("10039999") is None


def test_atom_sidecar_is_excluded_from_media_lookup(store, bucket):
    store.save("10030146", "vtex", "application/zip", b"zipbytes")
    store.save_entry("10030146", b"<entry/>")

    assert store.read("10030146") == b"zipbytes"
    assert store.read_entry("10030146") == b"<entry/>"
    assert store.extensions("10030146") == ["zip"]


def test_entry_is_stored_next_to_the_media(store, bucket):
    store.save_entry("10030146", b"<entry/>")
    assert "sword-deposits/1003/10030146.atom" in bucket.objects


def test_read_entry_is_none_when_absent(store):
    assert store.read_entry("10030146") is None


def test_ownership_check(store):
    store.save("10030146", "vtex", "application/zip", b"x")
    assert store.owned_by("10030146", "vtex")
    assert not store.owned_by("10030146", "mscmt")


def test_unsupported_media_type_is_refused_before_upload(store, bucket):
    with pytest.raises(SwordFault) as excinfo:
        store.save("10030146", "vtex", "text/plain", b"x")
    assert excinfo.value.status == 415
    assert bucket.objects == {}


def test_prefix_is_configurable(bucket):
    store = GsDepositStore(gs_bucket="b", gs_prefix="custom/place",
                           client=FakeClient(bucket))
    store.save("10030146", "vtex", "application/zip", b"x")
    assert "custom/place/1003/10030146.zip" in bucket.objects


# -------------------------------------------------------------------- ownership


def test_owner_from_the_media_blob(store):
    """A media deposit records its owner on the media object."""
    store.save("10030146", "vtex", "application/zip", b"x")
    assert store.owner_of("10030146") == "vtex"
    assert store.owned_by("10030146", "vtex")


def test_owner_from_the_entry_when_there_is_no_media(store):
    """A wrapper deposit stores only an entry, so that is where its owner lives.
    Without this, a depositor could not retrieve their own wrapper entry.
    """
    store.save_entry("10030147", b"<entry/>", owner="vtex")
    assert store.owner_of("10030147") == "vtex"
    assert store.owned_by("10030147", "vtex")
    assert not store.owned_by("10030147", "mscmt")


def test_entry_owner_wins_over_media_owner(store):
    store.save("10030148", "vtex", "application/zip", b"x")
    store.save_entry("10030148", b"<entry/>", owner="vtex")
    assert store.owner_of("10030148") == "vtex"


def test_entry_without_an_owner_falls_back_to_the_media_blob(store):
    """save_entry(owner=None) leaves the media object as the only record."""
    store.save("10030149", "vtex", "application/zip", b"x")
    store.save_entry("10030149", b"<entry/>")
    assert store.owner_of("10030149") == "vtex"


def test_unknown_deposit_has_no_owner(store):
    assert store.owner_of("10039999") is None
    assert not store.owned_by("10039999", "vtex")
