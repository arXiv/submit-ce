"""API for CompileService."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional

from submit_ce.api.domain import Submission, User, Client
from submit_ce.api.domain.event.process import Result
from submit_ce.api.domain.process import ProcessStatus
from submit_ce.api.submit import SubmitApi


class CompileService(ABC):
    """
    CompileService abstract base class.
    """

    @abstractmethod
    def start_compile(self, submission: Submission, user: User, client: Client,
                      api: SubmitApi,
                      source_package_id: Optional[str] = None) -> Result:
        """
        Start a compile process.

        Parameters
        ----------
        submission : Submission
            Instance to compile for.
        user : User
            Person requesting the compile
        client : Client
            Software client the user is making the request with.
        api : SubmitApi
            For implementations to access needed resources in the API.
        source_package_id : Optional[str]
            If this is `None` then the latest source package on the submission will be compiled.
        """
        ...

    @abstractmethod
    def check(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        """
        Check if there is a result for a compile process.

        Parameters
        ----------
        process_id: str
            Check for this process id.
        user: User
            Represents the Person requesting the check.
        client: Client
            The software client the user is making the request with.

        Returns
        -------
        ProcessStatus
        """
