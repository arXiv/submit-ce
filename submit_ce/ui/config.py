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

    MAX_UNCOMPRESSED_TOTAL_KB: int = 50_000
    """Max total uncompressed submission size, in KB, before the submission is
    flagged oversize (default 50 MB; the legacy arXiv size guideline)."""

    MAX_UNCOMPRESSED_PER_FILE_KB: int = 50_000
    """Max uncompressed size of any single file, in KB, before the submission
    is flagged oversize (default 50 MB)."""

    MAX_COMPRESSED_KB: int = 50_000
    """Max compressed upload size, in KB. Defined for completeness; not
    currently enforced (matches legacy check_sizes)."""

    COMPILE_API_URL: str = "https://tex2pdf-api-default-874717964009.us-central1.run.app"
    """The tex2pdf-api url.
    Do not end with a /.
    """

    COMPILE_API_MAX_RETRIES: int = 1

    COMPILE_API_RETRY_DELAY: int = 10

    COMPILE_API_PREFLIGHT_TIMEOUT: int = 840

    COMPILE_API_CONVERT_TIMEOUT: int = 840

    COMPILE_API_IMPERSONATE_SA: str = ""
    """Service account email to impersonate when minting ID tokens for the
    tex2pdf-api Cloud Run service. Leave empty in production (the attached
    runtime SA is used via the metadata server). Set locally to e.g.
    submit-ce-dev-sa@arxiv-development.iam.gserviceaccount.com."""

settings = Settings()
arxivbase_settings.CLASSIC_DB_URI = settings.CLASSIC_DB_URI
