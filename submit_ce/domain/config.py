"""Domain-facing configuration for the submission API.

`SubmitConfig` is a small, immutable bundle of the config values the *domain*
layer needs (for example, when an event composes an email). It deliberately
exposes only domain-relevant values, not the full application `Settings` (which
also carries implementation details like DB URIs and SMTP credentials). An
implementation builds one from its own settings and returns it via
`SubmitApi.get_config()`.
"""
from typing import Union

from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings


class SubmitConfig(BaseModel):
    """Domain-relevant configuration values, supplied by the `SubmitApi`."""

    model_config = ConfigDict(frozen=True)

    email_reply_to: str = "www-admin@arxiv.org"
    """``Reply-To`` address for normal submission confirmation emails."""

    email_auto_hold_reply_to: str = "mod-lib@arxiv.org"
    """``Reply-To`` address for auto-hold confirmation emails; replies go to
    the moderation team rather than the general admin address."""

    url_for_user_dashboard: str = "https://arxiv.org/user/"
    """Absolute URL of the user submission dashboard."""

    @classmethod
    def from_config(cls, config: Union[dict, BaseSettings]) -> "SubmitConfig":
        """Build a `SubmitConfig` from a dict or a `Settings`.
        Only the domain-relevant keys are read.
        """
        if not isinstance(config, dict):
            config = config.model_dump()

        defaults = cls()
        email_reply_to = config.get("EMAIL_REPLY_TO", defaults.email_reply_to)
        email_auto_hold_reply_to = config.get(
            "EMAIL_AUTO_HOLD_REPLY_TO", defaults.email_auto_hold_reply_to)

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

        return cls(email_reply_to=email_reply_to,
                   email_auto_hold_reply_to=email_auto_hold_reply_to,
                   url_for_user_dashboard=dashboard)
