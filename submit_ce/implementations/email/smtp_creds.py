"""SMTP credential resolution via GCP Secret Manager.

The secret's value must be an SMTP URI:

    smtps://user:password@host:port          (SSL — default for Halon)
    smtp+starttls://user:password@host:port  (STARTTLS)
    smtp://user:password@host:port           (plain, no encryption)

The short name form (e.g. ``"HALON_CREDS"``) requires ``GOOGLE_CLOUD_PROJECT``
to be set; a full ``projects/.../secrets/.../versions/...`` resource name is
passed straight through.

``smtp_creds_from_secret`` is cached for the process lifetime — a restart is
needed to pick up secret rotation.
"""
import os
from dataclasses import dataclass
from functools import cache
from urllib.parse import unquote, urlparse

import logging
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpCreds:
    host: str
    port: int | None
    user: str
    password: str
    use_ssl: bool
    use_starttls: bool

    @classmethod
    def parse(cls, url: str) -> "SmtpCreds":
        """Parse an SMTP URI into an ``SmtpCreds``."""
        parsed = urlparse(url)
        if not parsed.hostname:
            raise RuntimeError("SMTP URI secret value must include a hostname")
        return cls(
            host=parsed.hostname,
            port=parsed.port,
            user=unquote(parsed.username) if parsed.username else "",
            password=unquote(parsed.password) if parsed.password else "",
            use_ssl=parsed.scheme == "smtps",
            use_starttls=parsed.scheme == "smtp+starttls",
        )


def _resolve_secret_resource(name: str) -> str:
    """Accept either a full Secret Manager resource name or a short name."""
    if name.startswith("projects/"):
        return name
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if not project:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT must be set to resolve short secret name "
            f"{name!r}, or pass a full projects/.../secrets/.../versions/... resource"
        )
    return f"projects/{project}/secrets/{name}/versions/latest"


@cache
def smtp_creds_from_secret(secret_name: str) -> SmtpCreds:
    """Fetch and parse SMTP credentials from GCP Secret Manager.

    Cached for the process lifetime; a restart is required after secret
    rotation. The ``google-cloud-secret-manager`` package is imported here
    so it is only required when HALON mode is actually used.
    """
    from google.cloud import secretmanager  # noqa: PLC0415

    resource = _resolve_secret_resource(secret_name)
    logger.info("Fetching SMTP credentials from secret %r", resource)
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": resource})
    return SmtpCreds.parse(response.payload.data.decode("utf-8"))
