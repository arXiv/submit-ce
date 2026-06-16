import os
from typing import Literal, Tuple, List

from arxiv.config import settings as arxivbase_settings, Settings as ArxivBaseSettings


DEV_SQLITE_FILE="legacy.db"

SUBMIT_API_CONFIG_PREFIX="SUBMIT_API_"
"""Env vars starting with this will configure the submit api client."""


class Settings(ArxivBaseSettings):
    def __init__(self, **kwargs):
        super().__init__(kwargs)

        # gets all SUBMIT_API_ env vars and tries to make them into configs
        combined_dict = kwargs.copy()
        for key, value in os.environ.items():
            if key.startswith(SUBMIT_API_CONFIG_PREFIX):
                env_key = key[len(SUBMIT_API_CONFIG_PREFIX):]  # Remove prefix
                combined_dict[env_key.lower()] = value
        if "host" not in combined_dict:
            combined_dict["host"] = "http://localhost:8000"

        self.api_config = combined_dict

        if "CLASSIC_DB_URI" not in os.environ:
            self.CLASSIC_DB_URI = f"sqlite:///{DEV_SQLITE_FILE}"

        self.URLS = [
            ("help_license", "/help/license", self.BASE_SERVER),
            ("help_third_party_submission", "/help/third_party_submission",
             self.BASE_SERVER),
            ("help_cross", "/help/cross", self.BASE_SERVER),
            ("help_submit", "/help/submit", self.BASE_SERVER),
            ("help_ancillary_files", "/help/ancillary_files", self.BASE_SERVER),
            ("help_texlive", "/help/faq/texlive", self.BASE_SERVER),
            ("help_whytex", "/help/faq/whytex", self.BASE_SERVER),
            ("help_default_packages", "/help/submit_tex#wegotem", self.BASE_SERVER),
            ("help_submit_tex", "/help/submit_tex", self.BASE_SERVER),
            ("help_submit_pdf", "/help/submit_pdf", self.BASE_SERVER),
            ("help_submit_ps", "/help/submit_ps", self.BASE_SERVER),
            ("help_submit_html", "/help/submit_html", self.BASE_SERVER),
            ("help_submit_sizes", "/help/sizes", self.BASE_SERVER),
            ("help_metadata", "/help/prep", self.BASE_SERVER),
            ("help_jref", "/help/jref", self.BASE_SERVER),
            ("help_withdraw", "/help/withdraw", self.BASE_SERVER),
            ("help_replace", "/help/replace", self.BASE_SERVER),
            ("help_endorse", "/help/endorsement", self.BASE_SERVER),
            ("clickthrough", "/ct?url=<url>&v=<v>", self.BASE_SERVER),
            ("help_endorse", "/help/endorsement", self.BASE_SERVER),
            ("help_replace", "/help/replace", self.BASE_SERVER),
            ("help_version", "/help/replace#versions", self.BASE_SERVER),
            ("help_email", "/help/email-protection", self.BASE_SERVER),
            ("help_author", "/help/prep#author", self.BASE_SERVER),
            ("help_mistakes", "/help/faq/mistakes", self.BASE_SERVER),
            ("help_texprobs", "/help/faq/texprobs", self.BASE_SERVER),
            ("login", "/user/login", self.BASE_SERVER)
        ]

    api_config: dict = {}
    """Configuration to submit backend API. 
     
     Can be set with envvars that are prefixed with SUBMIT_API_{SOMETHING}.
     Ex. SUBMIT_API_HOST=http://localhost:8000"""

    #submission_api_implementation: ImportString = 'submit_ce.implementations.legacy_implementation.implementation'
    """Class to use for submission API implementation."""

    CSRF_SECRET: str = "foobar"
    """Used to make the CSRF secret on web forms. Must be the same for all
    distributed instances of submit-ce."""

    CLASSIC_DB_URI: str = f"sqlite:///{DEV_SQLITE_FILE}"
    
    URLS: List[Tuple[str, str, str]] = []
    """
    URLs for external services, for use with :func:`flask.url_for`.
    This subset of URLs is common only within submit, for now - maybe move to base
    if these pages seem relevant to other services.

    For details, see :mod:`arxiv.base.urls`.
    """

    JWT_SECRET: str = "foobar"
    """Used to encoded and decode JWTs for auth."""

    STORE: Literal["gs", "null"] = "gs"

    STORE_GS_BUCKET: str = "arxiv-submit-dev"
    """If in gs mode, what bucket to store submissions in."""
    
    STORE_GS_PREFIX: str = ""
    """A subdirectory to upload files related to your local database, ie: "api-test/myusername"
    """

    ADMIN_ONLY: bool = False
    """If true, only admin users can use the system. Intended to
    allowe closed to the public dev or beta system."""

    COMPILE_API_URL: str = "https://tex2pdf-api-default-874717964009.us-central1.run.app"
    """The tex2pdf-api url.
    Do not end with a /.
    """

    COMPILE_API_MAX_RETRIES: int = 1

    COMPILE_API_RETRY_DELAY: int = 10

    COMPILE_API_PREFLIGHT_TIMEOUT: int = 840

    COMPILE_API_CONVERT_TIMEOUT: int = 840

    EMAIL_MODE: Literal["TESTING", "HALON"] = "TESTING"
    """Which `EmailService` the app uses. ``HALON`` sends real mail via the
    Halon SMTP server (requires ``EMAIL_SMTP_SECRET`` to resolve);
    ``TESTING`` uses an in-memory service that captures messages instead of
    sending them. Defaults to ``TESTING`` so the app starts safely without
    GCP credentials; set ``EMAIL_MODE=HALON`` in production."""

    EMAIL_SMTP_SECRET: str = "HALON_CREDS"
    """Name of the GCP Secret Manager secret whose value is an SMTP URI
    (e.g. ``smtps://user:pass@mailh.arxiv.org:465``).
    A short name (e.g. ``"HALON_CREDS"``) is resolved against
    ``GOOGLE_CLOUD_PROJECT``; a full ``projects/…/secrets/…/versions/…``
    resource name is passed straight through. Only used when
    ``EMAIL_MODE=HALON``."""

    EMAIL_TIMEOUT: float = 10.0
    """Timeout in seconds for SMTP connection and I/O. Applied to both the
    initial connection and all blocking socket operations (login, send).
    Only used when ``EMAIL_MODE=HALON``."""

    EMAIL_FROM: str = "EMAIL_FROM@example.org"
    """Default ``From`` address for outgoing mail. Matches legacy submission mail."""

    EMAIL_REPLY_TO: str = "EMAIL_REPLY_TO@example.org"
    """``Reply-To`` address for email. Matches legacy, which used the
    configurable ``$WWW_ADMIN_ADDRESS``."""

    EMAIL_AUTO_HOLD_REPLY_TO: str = "EMAIL_AUTO_HOLD_REPLY_TO@example.org"
    """``Reply-To`` address for auto-hold confirmation emails so replies go to
    the moderation team."""

    MOD_REPLY_TO_EMAIL: str = "MOD_ADMIN_EMAIL@example.org"
    """Moderation admin address; included in ``Reply-To`` on moderator
    notification emails (e.g. category proposals)."""

    ARCHIVAL_EMAIL: str = "LOCAL_ADMIN_EMAIL@example.org"
    """Internal admin address; ``Bcc``'d on moderator notification emails, and
    the ``To`` fallback when a proposed category has no moderators."""

    COMPILE_API_IMPERSONATE_SA: str = ""
    """Service account email to impersonate when minting ID tokens for the
    tex2pdf-api Cloud Run service. Leave empty in production (the attached
    runtime SA is used via the metadata server). Set locally to e.g.
    submit-ce-dev-sa@arxiv-development.iam.gserviceaccount.com."""

settings = Settings()
arxivbase_settings.CLASSIC_DB_URI = settings.CLASSIC_DB_URI
