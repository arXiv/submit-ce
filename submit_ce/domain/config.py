"""Domain-facing configuration for the submission API.

`SubmitConfig` is a small, immutable bundle of the config values the *domain*
layer needs (for example, when an event composes an email). It deliberately
exposes only domain-relevant values, not the full application `Settings`. This
is to avoid unwanted exposure in the api of implementation details like DB URIs
and SMTP credentials.

An implementation builds one from its own settings and returns it via
`SubmitApi.get_config()`.
"""
from typing import Union

from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings


class SubmitConfig(BaseModel):
    """Domain-relevant configuration values, supplied by the `SubmitApi`."""

    model_config = ConfigDict(frozen=True)

    email_reply_to: str = "email_reply_to@arxiv.example.com"
    """``Reply-To`` address for normal submission confirmation emails.
    Real value read from ``Settings.EMAIL_REPLY_TO``."""

    email_auto_hold_reply_to: str = "email_auto_hold_reply_to@arxiv.example.com"
    """``Reply-To`` address for auto-hold confirmation emails; replies go to
    the moderation team rather than the general admin address.
    Real value read from ``Settings.EMAIL_AUTO_HOLD_REPLY_TO``."""

    url_for_user_dashboard: str = "https://arxiv.org/user/"
    """Absolute URL of the user submission dashboard."""

    mod_reply_to_email: str = "mod_reply_to_email@arxiv.example.com"
    """Moderation admin address; included in ``Reply-To`` on moderator emails.
    Real value read from ``Settings.MOD_REPLY_TO_EMAIL``."""

    archival_email: str = "archival_email@arxiv.example.com"
    """Internal admin address; ``Bcc``'d on moderator emails (and the ``To``
    fallback when a category has no moderators).
    Real value read from ``Settings.ARCHIVAL_EMAIL``."""

    @classmethod
    def from_config(cls, config: Union[dict, BaseSettings]) -> "SubmitConfig":
        """Build a `SubmitConfig` from a dict or a `Settings`.
        Only the domain-relevant keys are read.
        """
        if not isinstance(config, dict):
            config = config.model_dump()

        defaults = cls()

        dashboard = config.get("url_for_user_dashboard")
        if dashboard is None:
            base_server = config.get("BASE_SERVER")
            if base_server:
                host = base_server.rstrip("/")
                if not host.startswith(("http://", "https://")):
                    host = f"https://{host}"
                dashboard = f"{host}/user/"
            else:
                dashboard = defaults.url_for_user_dashboard

        return cls(email_reply_to=config.get("EMAIL_REPLY_TO", defaults.email_reply_to),
                   email_auto_hold_reply_to=config.get("EMAIL_AUTO_HOLD_REPLY_TO",
                                                       defaults.email_auto_hold_reply_to),
                   mod_reply_to_email=config.get("MOD_REPLY_TO_EMAIL",
                                              defaults.mod_reply_to_email),
                   archival_email=config.get("ARCHIVAL_EMAIL",
                                                 defaults.archival_email),
                   url_for_user_dashboard=dashboard,
                   )
