"""Email service implementations.

`HalonEmailService` is the production `EmailService`. It dispatches mail
through arXiv's Halon SMTP server over an authenticated SMTP-over-SSL
connection, using the standard library ``smtplib``/``email`` modules.
"""
import logging
import smtplib
from email.message import EmailMessage
from email.utils import format_datetime, localtime, make_msgid

from typing_extensions import override

from submit_ce.api.email_service import EmailService

logger = logging.getLogger(__name__)


class HalonEmailService(EmailService):
    """`EmailService` that sends mail via arXiv's Halon SMTP server.

    Connects to the Halon server over SMTP-over-SSL, authenticates, and
    sends a single text-body message.

    Parameters
    ----------
    host : str
        Hostname of the Halon SMTP server.
    user : str
        Username for SMTP authentication.
    password : str
        Password for SMTP authentication.
    from_address : str
        Default ``From`` address for outgoing mail.
    port : int
        Port for the SMTP connection. Defaults to 465.
    use_starttls : bool
        If ``True``, connect with plain SMTP then upgrade via STARTTLS.
        If ``False`` (default), connect with SMTP_SSL.
    """

    def __init__(self,
                 host: str,
                 user: str,
                 password: str,
                 from_address: str,
                 port: int = 465,
                 use_starttls: bool = False,
                 timeout: float = 30.0) -> None:
        self.host = host
        self.user = user
        self.password = password
        self.from_address = from_address
        self.port = port
        self.use_starttls = use_starttls
        self.timeout = timeout

    def __repr__(self) -> str:
        # Never include the password in a repr.
        return (f"{self.__class__.__name__}("
                f"host={self.host!r},"
                f"port={self.port!r},"
                f"user={self.user!r},"
                f"from_address={self.from_address!r}"
                ")")

    @override
    def send_email(self,
                   to: list[str],
                   subject: str,
                   body: str,
                   reply_to: str,
                   cc: list[str] | None = None,
                   bcc: list[str] | None = None,
                   message_id: str = "",
                   references: str = "") -> tuple[str,str]:
        """Build and send a plain-text email through the Halon server.

        Parameters match `EmailService.send_email`; see that method for
        details. ``Bcc`` recipients are included in the SMTP envelope but
        not in the message headers.
        """
        cc = cc or []
        bcc = bcc or []

        msg = EmailMessage()
        msg["Date"] = format_datetime(localtime())
        msg["Message-ID"] = message_id or make_msgid()
        msg["From"] = self.from_address
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(cc)
        if reply_to:
            msg["Reply-To"] = reply_to
        if references:
            msg["References"] = references

        # cte='8bit' and 8bitmime mail option avoids needless down-coding of the body.
        # Recomended in halon docs.
        msg.set_content(body, cte="8bit")
        mail_options=("8bitmime",)

        # Envelope recipients: every address that should receive the mail,
        # including Bcc (which is intentionally absent from the headers).
        recipients = list(to) + list(cc) + list(bcc)

        try:
            if self.use_starttls:
                with smtplib.SMTP(host=self.host, port=self.port, timeout=self.timeout) as sess:
                    sess.starttls()
                    sess.login(self.user, self.password)
                    refused = sess.send_message(msg,
                                                from_addr=self.from_address,
                                                to_addrs=recipients,
                                                mail_options=mail_options)
            else:
                with smtplib.SMTP_SSL(host=self.host, port=self.port, timeout=self.timeout) as sess:
                    sess.login(self.user, self.password)
                    refused = sess.send_message(msg,
                                                from_addr=self.from_address,
                                                to_addrs=recipients,
                                                mail_options=mail_options)
        except TimeoutError:
            return (msg["Message-ID"],
                    f"Email timed out after {self.timeout}s"
                    f" connecting to {self.host}:{self.port}")
        except smtplib.SMTPAuthenticationError as e:
            return (msg["Message-ID"],
                    f"SMTP authentication failed for user {self.user!r}:"
                    f" {e.smtp_error.decode(errors='replace')}")
        except smtplib.SMTPConnectError as e:
            return (msg["Message-ID"],
                    f"Could not connect to SMTP server {self.host}:{self.port}:"
                    f" {e.smtp_error.decode(errors='replace')}")
        except smtplib.SMTPRecipientsRefused as e:
            parts = ", ".join(
                f"{addr} ({code}, {resp.decode(errors='replace')})"
                for addr, (code, resp) in e.recipients.items()
            )
            return (msg["Message-ID"], f"All recipients refused: {parts}")
        except smtplib.SMTPSenderRefused as e:
            return (msg["Message-ID"],
                    f"Sender {self.from_address!r} refused:"
                    f" {e.smtp_error.decode(errors='replace')}")

        if refused:
            parts = ", ".join(
                f"{addr} ({code}, {resp.decode(errors='replace')})"
                for addr, (code, resp) in refused.items()
            )
            logger.warning("send_email %s: some recipients refused: %s",
                           msg["Message-ID"], parts)
            return (msg["Message-ID"],
                    f"Email sent but some recipients refused: {parts}")

        logger.info("Sent email %s to %d recipient(s)",
                    msg["Message-ID"], len(recipients))
        return (msg["Message-ID"], "")

    @override
    def is_available(self) -> bool:
        """Return ``True`` if the service has the config needed to send.

        This checks configuration only; it does not open a connection to
        the SMTP server.
        """
        return bool(self.host and self.user and self.password
                    and self.from_address)
