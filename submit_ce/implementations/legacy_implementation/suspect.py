"""The general-category routing check of legacy ``route_to_gen``.

Ported from ``arXiv::Schema::Result::Submission::route_to_gen`` and
``arXiv::Submit::Suspect::route_to_genph`` (``Suspect.pm:37-56``). SUBMISSION-39.
Unlike the Perl, a pattern Python cannot compile is skipped rather than fatal,
and some Perl regex syntax may not match as it does in Perl.
"""

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session as SQLAlchemySession

from . import models

logger = logging.getLogger(__name__)


def routes_to_general_category(session: SQLAlchemySession, user_id: str,
                               email: str) -> bool:
    """Whether legacy routes this submitter's new submissions to a general category.

    Admins (``flag_edit_users``) never are. Anyone else is when a ``GENPH``
    pattern in ``arXiv_suspect_emails`` matches their email, searched as a
    case-insensitive regex.
    """
    user = session.get(models.User, int(user_id))
    if user is not None and user.flag_edit_users:
        return False
    rows = session.execute(select(models.SuspectEmail.id, models.SuspectEmail.pattern)
                           .where(models.SuspectEmail.type == 'GENPH'))
    for row_id, pattern in rows:
        try:
            if re.search(f'({pattern})', email, re.IGNORECASE):  # Perl: /($pattern)/i
                return True
        except re.error:
            logger.warning("Skipping arXiv_suspect_emails id %s: not a valid regex", row_id)
    return False
