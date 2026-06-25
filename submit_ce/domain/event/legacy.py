"""Events that are intended to be backward compatable with legacy submit 1.5."""


from pydantic import ConfigDict, Field
from submit_ce.api.submit import SubmitApi
from submit_ce.domain.event.base import Event, EventWithSideEffect
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.submission import Submission
from submit_ce.domain.uploads import InMemorySubmitFile, SourceFormat

class Withdraw(EventWithSideEffect):
    """Make a submission for a older style paper withdraw aka `wdr`."""

    NAME = "withdraw"
    NAMED = "withdrawn"

    paper_id: str
    """Announced arXiv id of the paper being withdrawn."""

    comment: str = Field(min_length=10, max_length=400)
    """Reason for the withdrawal; appended to the row's Comments."""

    abstract: str = Field(min_length=10, max_length=1920)
    """Updated abstract for the withdrawal notice."""

    def validate_pre_lock(self, submission: Submission) -> None:
        """Make sure that a reason was provided and the paper is announced."""
        if not self.comment:
            raise InvalidEvent(self, "Provide a reason for the withdrawal")
        if not submission.is_announced:
            raise InvalidEvent(self, "Submission must already be announced")

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Make the file for the withdraw."""
        content = '%auto-ignore'
        file_store = api.get_file_store()
        withdrawn_file = InMemorySubmitFile("withdrawn", content.encode("utf-8"))
        file_store.delete_all_source_files(str(submission.submission_id))
        file_store.store_source_file(str(submission.submission_id),
                                     withdrawn_file, chunk_size=4096)

    def project(self, submission: Submission) -> Submission:
        """Set the withdrawal source state and updated abstract.

        The withdrawal reason (`comments`) is recorded on the classic row via
        the `WDR_DELIMETER` mechanism during persistence, not here.
        """
        assert self.created is not None
        submission.source_format = SourceFormat.WITHDRAWN
        submission.is_source_processed = True
        submission.metadata.abstract = self.abstract
        return submission


class _LegacyUploadPackageEvent(Event):
    """Base for the removed ``*UploadPackage`` events, kept as a no-op shim.

    ``SetUploadPackage`` / ``UpdateUploadPackage`` / ``UnsetUploadPackage`` were
    removed in commit ``20e2a47`` ("Refactor to remove XyzUploadPackage event
    classes"); source/file state now comes from the FileStore workspace and the
    events in :mod:`submit_ce.domain.event.file`. Submissions created before
    that refactor still have these rows persisted, so without a matching class
    :meth:`models.DBEvent.to_event` raises ``Unknown event type`` and the whole
    submission fails to load. These shims exist only so those old rows
    deserialize and replay. The field they once projected onto
    (``Submission.source_content``) no longer exists, so projection is a pure
    no-op and validation always passes.
    """
    model_config = ConfigDict(extra="ignore")  # tolerate old payload fields

    def validate_pre_lock(self, submission: Submission) -> None:
        """No-op: legacy event, nothing to validate."""
        return None

    def project(self, submission: Submission) -> Submission:
        """No-op: legacy event, leaves the submission unchanged."""
        return submission


class SetUploadPackage(_LegacyUploadPackageEvent):
    """Deprecated no-op shim; see :class:`_LegacyUploadPackageEvent`."""

    NAME = "set the upload package (legacy no-op)"
    NAMED = "upload package set"


class UpdateUploadPackage(_LegacyUploadPackageEvent):
    """Deprecated no-op shim; see :class:`_LegacyUploadPackageEvent`."""

    NAME = "update the upload package (legacy no-op)"
    NAMED = "upload package updated"


class UnsetUploadPackage(_LegacyUploadPackageEvent):
    """Deprecated no-op shim; see :class:`_LegacyUploadPackageEvent`."""

    NAME = "unset the upload package (legacy no-op)"
    NAMED = "upload package unset"
