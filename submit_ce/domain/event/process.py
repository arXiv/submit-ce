"""Events related to external or long-running processes."""
from datetime import datetime
from typing import Optional

from dataclasses import field

from pydantic import BaseModel

from ..exceptions import InvalidEvent
from ..submission import Submission
from ..process import ProcessStatus
from .base import Event, EventWithSideEffect

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ... import SubmitApi


class ProcessInfo(BaseModel):
    process_id: str
    """Identifier for the specific running process."""
    service_id: str
    """Identifier for the service running the process."""

class Result(BaseModel):
    """Result of a process such as compile."""
    status: ProcessStatus
    """The status of the process."""
    duration_sec: Optional[float]
    """Wall clock duration of the process in seconds."""
    utc_start_time: Optional[datetime]
    """UTC start time of the process."""
    url: Optional[str]
    """URL for the result of the process."""

class StartCompileSource(EventWithSideEffect):
    """Start compile the source of a submission."""

    NAME = "compile source"
    NAMED = "compiled source"

    source_content_id: Optional[str] = field(default=None)
    process: Optional[ProcessInfo] = field(default=None)
    result: Optional[Result] = field(default=None)

    def __post_init__(self) -> None:
        """Make sure our enums are in order."""
        super(StartCompileSource, self).__post_init__()

    def validate(self, submission: Submission) -> None:
        """Verify that we have a :class:`.ProcessStatus`."""
        if submission.uncompressed_size <= 0:
            raise InvalidEvent(self, "Compile source for the submission is empty.")

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Do the actual compile."""
        result = api.get_compiler().start_compile(submission,
                                                  self.creator,
                                                  self.client,
                                                  api,
                                                  submission.submission_id)
        self.source_content_id = submission.submission_id
        # TODO add process info to Event?
        #self.process = process
        self.result = result

    def project(self, submission: Submission) -> Submission:
        """Add the process status to the submission."""
        assert self.created is not None
        #assert self.process is not None
        #assert self.status is not None and self.status in ProcessStatus.Status
        submission.processes.append(StartCompileSource(
            creator=self.creator,
            created=self.created,
            source_content_id=self.source_content_id,
            process=self.process,
            result=self.result,
        ))
        return submission


class StartPreflight(EventWithSideEffect):
    """Start preflight checks for a submission."""

    NAME = "start preflight"
    NAMED = "started preflight"

    source_content_id: Optional[str] = field(default=None)
    process: Optional[ProcessInfo] = field(default=None)
    result: Optional[Result] = field(default=None)

    def __post_init__(self) -> None:
        super(StartPreflight, self).__post_init__()

    def validate(self, submission: Submission) -> None:
        if not submission.submission_id:
            raise InvalidEvent(self, "Source content for preflight is empty.")

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Run preflight checks."""
        result = api.get_compiler().start_preflight(
                submission,
                self.creator,
                self.client,
                api,
                submission.submission_id
        )
        self.source_content_id = submission.submission_id
        # TODO add process info to Event?
        #self.process = process
        self.result = result

    def project(self, submission: Submission) -> Submission:
        assert self.created is not None
        submission.processes.append(StartPreflight(
            creator=self.creator,
            created=self.created,
            source_content_id=self.source_content_id,
            process=self.process,
            result=self.result,
        ))
        return submission


class BuildSourcePackage(EventWithSideEffect):
    """Build the canonical ``<id>.tar.gz`` source package under the lock.

    The tar is assembled from the submission's current source files. By
    running as an :class:`.EventWithSideEffect`, ``SubmitApi.save`` holds the
    submission row lock for the duration of :meth:`execute`, so a concurrent
    upload or delete cannot change the file set mid-build and produce a
    package that mixes files which never coexisted on the submission. See the
    "critical section" design note in ``CLAUDE.md``.

    Carries no extra data (the side effect is the persisted ``<id>.tar.gz``),
    so it serializes and replays like any base event.
    """

    NAME = "build source package"
    NAMED = "built source package"

    def validate(self, submission: Submission) -> None:
        """The submission must exist to have a source package built."""
        if not submission.submission_id:
            raise InvalidEvent(
                self, "Cannot build source package: submission has no id.")

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Build and persist ``<id>.tar.gz`` from current source, under lock."""
        api.get_file_store().write_source_package(submission.submission_id)

    def project(self, submission: Submission) -> Submission:
        """No submission-state change; the side effect is the stored tar."""
        return submission


class StartDirectives(EventWithSideEffect):
    """Start directives generation for a submission."""

    NAME = "start directives"
    NAMED = "started directives"

    source_content_id: Optional[str] = field(default=None)
    process: Optional[ProcessInfo] = field(default=None)
    result: Optional[Result] = field(default=None)

    def validate(self, submission: Submission) -> None:
        if not submission.submission_id:
            raise InvalidEvent(self, "Source content for directives is empty.")

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        result = api.get_compiler().start_directives(
                submission,
                self.creator,
                self.client,
                api,
                submission.submission_id
        )
        self.source_content_id = submission.submission_id
        self.result = result

    def project(self, submission: Submission) -> Submission:
        assert self.created is not None
        submission.processes.append(StartDirectives(
            creator=self.creator,
            created=self.created,
            source_content_id=self.source_content_id,
            process=self.process,
            result=self.result,
        ))
        return submission


class CompileStatus(Event):
    """Add the status of an external/long-running process to a submission."""

    NAME = "add status of a process"
    NAMED = "added status of a process"

    # Status = ProcessStatus.Status

    process: Optional[ProcessInfo] = field(default=None)
    result: Optional[Result] = field(default=None)

    def __post_init__(self) -> None:
        """Make sure our enums are in order."""
        super(CompileStatus, self).__post_init__()

    def validate(self, submission: Submission) -> None:
        """Verify that we have a :class:`.ProcessStatus`."""
        if self.process is None:
            raise InvalidEvent(self, "Must include process")
        if self.result is None:
            raise InvalidEvent(self, "Must include result")

    def project(self, submission: Submission) -> Submission:
        """Add the process status to the submission."""
        assert self.created is not None
        assert self.process is not None
        submission.processes.append(ProcessStatus(
            creator=self.creator,
            created=self.created,
            process=self.process,
            result=self.result,
        ))
        return submission


class PreflightStatus(Event):
    """Add the status of a preflight process to a submission."""

    NAME = "add status of preflight"
    NAMED = "added status of preflight"

    process: Optional[ProcessInfo] = field(default=None)
    result: Optional[Result] = field(default=None)

    def __post_init__(self) -> None:
        super(PreflightStatus, self).__post_init__()

    def validate(self, submission: Submission) -> None:
        if self.process is None:
            raise InvalidEvent(self, "Must include process")
        if self.result is None:
            raise InvalidEvent(self, "Must include result")

    def project(self, submission: Submission) -> Submission:
        assert self.created is not None
        assert self.process is not None
        submission.processes.append(ProcessStatus(
            creator=self.creator,
            created=self.created,
            process=self.process,
            result=self.result,
        ))
        return submission
