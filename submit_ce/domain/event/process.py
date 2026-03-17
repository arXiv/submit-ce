"""Events related to external or long-running processes."""
from datetime import datetime
from typing import Optional

from dataclasses import field

from pydantic import BaseModel

from ...exceptions import InvalidEvent
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
        if submission.source_content is None or not submission.source_content.identifier:
            raise InvalidEvent("Compile source for the submission is empty.")

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Do the actual compile."""
        result = api.get_compiler().start_compile(submission,
                                                  self.creator,
                                                  self.client,
                                                  api,
                                                  submission.source_content.identifier)
        self.source_content_id = submission.source_content.identifier
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
