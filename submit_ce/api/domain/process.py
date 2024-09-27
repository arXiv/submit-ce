"""Status information for external or long-running processes."""

from pydantic.dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from enum import Enum
from typing import Optional

from .agent import Agent


@dataclass
class ProcessStatus:
    """Represents the status of a long-running remote process."""

    class Status(Enum):
        """Supported statuses."""

        PENDING = 'pending'
        """The process is waiting to start."""
        IN_PROGRESS = 'in_progress'
        """Process has started, and is running remotely."""
        FAILED_TO_START = 'failed_to_start'
        """Could not start the process."""
        FAILED = 'failed'
        """The process failed while running."""
        FAILED_TO_END = 'failed_to_end'
        """The process ran, but failed to end gracefully."""
        SUCCEEDED = 'succeeded'
        """The process ended successfully."""
        TERMINATED = 'terminated'
        """The process was terminated, e.g. cancelled by operator."""

    creator: Agent
    created: datetime
    """Time when the process status was created (not the process itself)."""
    process: str
    step: Optional[str] = field(default=None)
    status: Status = field(default=Status.PENDING)
    reason: Optional[str] = field(default=None)
    """Optional context or explanatory details related to the status."""
