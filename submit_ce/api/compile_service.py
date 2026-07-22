"""API for CompileService."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional


if TYPE_CHECKING:
    from submit_ce.api.submit import SubmitApi
    from submit_ce.domain import Submission, User, Client
    from submit_ce.domain.event.process import Result
    from submit_ce.domain.process import ProcessStatus


class CompileService(ABC):
    """
    CompileService abstract base class.
    """

    @abstractmethod
    def start_directives(self,
            submission: Submission,
            user: User,
            client: Client,
            api: SubmitApi,
            source_package_id: Optional[str] = None,
    ) -> Result:
        """
        Start a directives process.

        Combines preflight output, user options, and compile logs to produce
        the ``directives.json`` blob that drives downstream compilation.

        Parameters
        ----------
        submission : Submission
            Instance to generate directives for.
        user : User
            Person requesting the directives.
        client : Client
            Software client the user is making the request with.
        api : SubmitApi
            For implementations to access needed resources in the API.
        source_package_id : Optional[str]
            If `None`, the latest source package on the submission is used.
        """
        ...

    @abstractmethod
    def check_directives(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        """
        Check if there is a result for a directives process.

        Parameters
        ----------
        process_id : str
            Check for this process id.
        user : User
            Represents the person requesting the check.
        client : Client
            The software client the user is making the request with.

        Returns
        -------
        ProcessStatus
        """
        ...

    @abstractmethod
    def start_preflight(self,
            submission: Submission,
            user: User,
            client: Client,
            api: SubmitApi,
            source_package_id: Optional[str] = None,
    ) -> Result:
        """
        Start a preflight process.

        Analyzes the submission's source files to detect TeX files, top-level
        candidates, and required assets, producing the ``gcp_preflight.json``
        blob consumed by the review-files stage.

        Parameters
        ----------
        submission : Submission
            Instance to run preflight on.
        user : User
            Person requesting preflight.
        client : Client
            Software client the user is making the request with.
        api : SubmitApi
            For implementations to access needed resources in the API.
        source_package_id : Optional[str]
            If `None`, the latest source package on the submission is used.
        """
        ...

    @abstractmethod
    def check_preflight(self, process_id: str, user: User, client: Client) -> ProcessStatus:
        """
        Check if there is a result for a preflight process.

        Parameters
        ----------
        process_id : str
            Check for this process id.
        user : User
            Represents the person requesting the check.
        client : Client
            The software client the user is making the request with.

        Returns
        -------
        ProcessStatus
        """
        ...

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
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the service is configured and available.

        Returns
        -------
        str
            `True` if service is configured and available.
        """
        ...

    @abstractmethod
    def stamp(self, pdf_bytes: bytes, watermark_text: str,
              watermark_link: Optional[str] = None) -> bytes:
        """
        Apply the temporary submission watermark/stamp to a PDF.

        Used for PDF-only submissions, which never run ``/convert`` (TeX
        submissions are stamped by the compile service during conversion).
        The stamped PDF is returned so the caller can install it; nothing is
        written to the file store here.

        Parameters
        ----------
        pdf_bytes : bytes
            The unstamped PDF.
        watermark_text : str
            Stamp text, e.g. ``arXiv:submit/1234567  [cs.LG]  15 Jan 2026``.
        watermark_link : Optional[str]
            Optional link embedded in the stamp.

        Returns
        -------
        bytes
            The stamped PDF.

        Raises
        ------
        Exception
            If stamping fails; the caller is expected to fall back to the
            unstamped PDF so the preview slot is never empty.
        """
        ...
