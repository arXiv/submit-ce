"""Moderators of categories and archives.

A :class:`.Moderator` is the resolution of a classic ``arXiv_moderators`` row to
a notifiable person: a user (with an email address) responsible for a category
or, when ``subject_class`` is empty, a whole archive. This is decoupled from
SQLAlchemy so the recipient-resolution logic and downstream email code do not
depend on the ORM.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Moderator:
    """A user assigned to moderate a category or an entire archive."""

    user_id: str
    email: str
    archive: str
    subject_class: str = ""
    """The subject class, or ``""`` for an archive-level moderator."""

    name: Optional[str] = field(default=None)

    no_email: bool = field(default=False)
    no_web_email: bool = field(default=False)
    no_reply_to: bool = field(default=False)

    @property
    def is_archive_level(self) -> bool:
        """Whether this moderator covers the whole archive."""
        return self.subject_class == ""

    @property
    def category(self) -> str:
        """The category id this assignment covers (archive id if archive-level)."""
        if self.is_archive_level:
            return self.archive
        return f"{self.archive}.{self.subject_class}"
