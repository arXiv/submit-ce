"""GCS-backed `DepositStore`.

Mirrors legacy's ``/cache/atomdeposits`` tree onto a bucket:

    <prefix>/nextid                    allocation counter
    <prefix>/<yymm>/<id>.<ext>         deposited bytes
    <prefix>/<yymm>/<id>.atom          the response entry

The ``flock`` legacy used on the counter (``AtomPP.pm:586-596``) becomes a
compare-and-swap on the object's generation: ``if_generation_match`` makes the
write conditional, and GCS answers 412 when another writer got there first. A
generation of ``0`` means "only if the object does not exist", which is how the
counter is created on first use.

Retention (>=30 days, ``submit_sword.md:744``) is a bucket lifecycle rule, not
something this class enforces.

Follows `submit_ce.implementations.file_store.gs_file_store.GsFileStore` in taking
an optional pre-configured ``client``, which is what lets the conditional-write
logic be tested without a network.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage

from submit_ce.sword.deposits import (
    COUNTER_OBJECT,
    DepositStore,
    StagedDeposit,
    extension_for,
    yymm_of,
)

logger = logging.getLogger(__name__)

INITIAL_COUNTER = 1
"""Value assumed when the counter object does not exist yet."""

OWNER_METADATA_KEY = "sword-owner"


class GsDepositStore(DepositStore):
    """Staging store on a GCS bucket."""

    def __init__(self,
                 gs_bucket: str,
                 gs_prefix: str = "sword-deposits",
                 client: Optional[storage.Client] = None):
        self.gs_bucket = gs_bucket
        self.gs_prefix = gs_prefix.strip("/")
        self.storage_client = client if client is not None else storage.Client()
        self.bucket = self.storage_client.bucket(gs_bucket)

    # -- paths ---------------------------------------------------------------

    def _counter_path(self) -> str:
        return f"{self.gs_prefix}/{COUNTER_OBJECT}"

    def _shard(self, deposit_id: str) -> str:
        return f"{self.gs_prefix}/{yymm_of(deposit_id)}"

    def _media_path(self, deposit_id: str, extension: str) -> str:
        return f"{self._shard(deposit_id)}/{deposit_id}.{extension}"

    def _entry_path(self, deposit_id: str) -> str:
        return f"{self._shard(deposit_id)}/{deposit_id}.atom"

    # -- counter -------------------------------------------------------------

    def _read_counter(self) -> Tuple[int, object]:
        blob = self.bucket.get_blob(self._counter_path())
        if blob is None:
            # Generation 0 is GCS's "this object must not exist" precondition.
            return INITIAL_COUNTER, 0
        raw = blob.download_as_bytes().strip()
        try:
            return int(raw), blob.generation
        except ValueError:
            logger.error("deposit counter at %s is not an integer: %r",
                         self._counter_path(), raw[:32])
            raise

    def _write_counter(self, value: int, version: object) -> bool:
        blob = self.bucket.blob(self._counter_path())
        try:
            blob.upload_from_string(str(value), content_type="text/plain",
                                    if_generation_match=version)
        except PreconditionFailed:
            logger.info("deposit counter changed under us; retrying")
            return False
        return True

    # -- storage -------------------------------------------------------------

    def save(self, deposit_id: str, owner: str, content_type: str,
             data: bytes) -> StagedDeposit:
        extension = extension_for(content_type)
        self.check_size(data)

        blob = self.bucket.blob(self._media_path(deposit_id, extension))
        blob.metadata = {OWNER_METADATA_KEY: owner}
        blob.upload_from_string(data, content_type=content_type)

        return StagedDeposit(
            deposit_id=deposit_id,
            owner=owner,
            extension=extension,
            content_type=content_type,
            size=len(data),
            created=datetime.now(timezone.utc),
        )

    def _find_media_blob(self, deposit_id: str):
        prefix = f"{self._shard(deposit_id)}/{deposit_id}."
        for blob in self.storage_client.list_blobs(self.bucket, prefix=prefix):
            if not blob.name.endswith(".atom"):
                return blob
        return None

    def get(self, deposit_id: str) -> Optional[StagedDeposit]:
        blob = self._find_media_blob(deposit_id)
        if blob is None:
            return None
        metadata = blob.metadata or {}
        return StagedDeposit(
            deposit_id=deposit_id,
            owner=metadata.get(OWNER_METADATA_KEY, ""),
            extension=blob.name.rsplit(".", 1)[-1],
            content_type=blob.content_type or "",
            size=blob.size or 0,
            created=blob.time_created or datetime.now(timezone.utc),
        )

    def read(self, deposit_id: str) -> Optional[bytes]:
        blob = self._find_media_blob(deposit_id)
        return blob.download_as_bytes() if blob is not None else None

    def save_entry(self, deposit_id: str, document: bytes) -> None:
        blob = self.bucket.blob(self._entry_path(deposit_id))
        blob.upload_from_string(document, content_type="application/atom+xml")

    def read_entry(self, deposit_id: str) -> Optional[bytes]:
        blob = self.bucket.get_blob(self._entry_path(deposit_id))
        return blob.download_as_bytes() if blob is not None else None

    def extensions(self, deposit_id: str) -> List[str]:
        prefix = f"{self._shard(deposit_id)}/{deposit_id}."
        return sorted(
            blob.name.rsplit(".", 1)[-1]
            for blob in self.storage_client.list_blobs(self.bucket, prefix=prefix)
            if not blob.name.endswith(".atom"))
