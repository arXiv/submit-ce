"""Events related to external or long-running processes."""
from datetime import datetime
import json
from typing import Optional

from dataclasses import field

from arxiv.files.object_store import FileDoesNotExist
from pydantic import BaseModel

from ..exceptions import InvalidEvent
from ..submission import Submission
from ..process import ProcessStatus
from .base import Event, EventWithSideEffect

from typing import TYPE_CHECKING

from submit_ce.api import SubmitApi


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


class SetDecisions(EventWithSideEffect):
    """Add the status of a preflight process to a submission."""

    NAME = "set compile decisions"
    NAMED = "set compile decisions"

    # TODO make this a pydantic class
    decisions: dict

    files_to_delete: list[str]

    bytes_removed: int = 0

    def validate(self, submission: Submission) -> None:
        if not self.decisions:
            raise InvalidEvent(self, "Must include decisions information")
        # TODO better validation of preflight data or just handled by pydantic?
        # Maybe have the prefight be a dict on self then validate it here and raise errors?

    def pre_execute_validation(self, api: SubmitApi, submission: Submission) -> None:
        blob = api.get_file_store().get_user_decisions(submission.submission_id)
        if isinstance(blob, FileDoesNotExist):
            return

        existing_preflight = json.loads(blob.download_as_text())
        decisions_changed = self.decisions != existing_preflight
        has_changes = bool(self.files_to_delete) or decisions_changed
        # TODO we could check if the files_to_delete actually exist
        if not has_changes:
            raise InvalidEvent(self, "No changes to save")

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        file_store = api.get_file_store()
        file_store.delete_preflight(submission.submission_id)
        file_store.store_user_decisions(submission.submission_id, self.decisions)
        for path in self.files_to_delete:
            file = file_store.delete_source_file(submission.submission_id, path)
            if file:
                self.bytes_removed += file.bytes

    def project(self, submission: Submission) -> Submission:
        submission -= self.bytes_removed
        return Submisison
