"""API for service to send email."""
from abc import ABCMeta, abstractmethod

class EmailService(metaclass=ABCMeta):
    @abstractmethod
    def send_email(self,
                   to: list[str],
                   subject: str,
                   body: str,
                   reply_to: str,
                   cc: str="",
                   bcc: str="",
                   message_id: str="",
                   references: str="") -> None:
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
        cc : str
            Address(es) to copy on the message. Pass empty string for no CCs.
        bcc : str
            Address(es) to blind-copy on the message. Pass empty string for no CCs.
        message_id : str
            Unique identifier for this message (the ``Message-ID`` header),
            used for threading.
        references : str
            ``References`` header linking this message to prior messages in
            a thread.
        """
        pass



    @abstractmethod
    def is_available(self) -> bool:
        """Determine whether the service is available."""
        pass
