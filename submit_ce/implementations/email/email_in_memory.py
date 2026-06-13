"""In-memory `EmailInMemory` service for tests.

A drop-in `EmailService` for unit and integration tests that retains sent
messages in process memory instead of dispatching them through a real mail
transport. Tests can send email exactly as production code would, then inspect
`sent` (or use the convenience accessors) to assert on what was sent.
"""
from dataclasses import dataclass, field

from submit_ce.api.email_service import EmailService


@dataclass(frozen=True)
class SentEmail:  # pragma: no cover
    """A single captured email.

    Mirrors the parameters of `EmailService.send_email`.
    """

    to: list[str]
    subject: str
    body: str
    reply_to: str
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    message_id: str = ""
    references: str = ""


class EmailInMemory(EmailService):  # pragma: no cover
    """An `EmailService` that captures sent email in memory for tests.

    Each call to `send_email` appends a `SentEmail` to `sent`, in order. The
    captured messages can then be examined to make assertions during a test.

    Examples
    --------
    >>> service = EmailInMemory()
    >>> service.send_email(["a@example.com"], "Hi", "Body", "noreply@arxiv.org")
    >>> len(service.sent)
    1
    >>> service.last.subject
    'Hi'
    >>> service.clear()
    >>> service.sent
    []
    """

    def __init__(self) -> None:
        self.sent: list[SentEmail] = []

    def send_email(self,
                   to: list[str],
                   subject: str,
                   body: str,
                   reply_to: str,
                   cc: list[str] | None = None,
                   bcc: list[str] | None = None,
                   message_id: str = "",
                   references: str = "") -> tuple[str, str]:
        """Capture an email in memory.

        Parameters match `EmailService.send_email`; see that method for
        details. The message is appended to `sent` rather than dispatched.
        """
        self.sent.append(SentEmail(
            to=list(to),
            subject=subject,
            body=body,
            reply_to=reply_to,
            cc=list(cc or []),
            bcc=list(bcc or []),
            message_id=message_id,
            references=references,
        ))
        return (message_id, "")

    @property
    def last(self) -> SentEmail:
        """Return the most recently sent email.

        Raises
        ------
        IndexError
            If no email has been sent.
        """
        return self.sent[-1]

    def clear(self) -> None:
        """Discard all captured emails."""
        self.sent.clear()

    def is_available(self) -> bool:
        return True
