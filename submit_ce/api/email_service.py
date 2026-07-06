"""API for service to send email."""
from abc import ABCMeta, abstractmethod

class EmailService(metaclass=ABCMeta):
    @abstractmethod
    def send_email(self,
                   to: list[str],
                   subject: str,
                   body: str,
                   reply_to: str,
                   cc: list[str] | None = None,
                   bcc: list[str] | None = None,
                   message_id: str="",
                   references: str="") -> tuple[str, str]:
        """Send an email.

        Parameters
        ----------
        to : list[str]
            Recipient email addresses.
        subject : str
            Subject line of the message.
        body : str
            Body content of the message.
        reply_to : str
            Address that replies should be directed to.
        cc : list[str], optional
            Addresses to copy on the message. Pass ``None`` or an empty list
            for no CCs.
        bcc : list[str], optional
            Addresses to blind-copy on the message. Pass ``None`` or an empty
            list for no BCCs.
        message_id : str
            Unique identifier for this message (the ``Message-ID`` header),
            used for threading.
        references : str
            ``References`` header linking this message to prior messages in
            a thread.

        Returns
        -------
        tuple[str, str]
            ``(message_id, error)``. ``error`` is an empty string on success,
            or a human-readable description if sending failed or some
            recipients were refused.
        """
        pass



    @abstractmethod
    def is_available(self) -> bool:
        """Determine whether the service is available."""
        pass
