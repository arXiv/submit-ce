"""Resolve which moderators should be notified for a set of categories.

A Python port of the legacy recipient logic
(``arXiv::Submit::Email::SubmissionEmailLists::get_mod_email_to`` plus
``CategoryDef::moderators`` / ``archive_moderators``): for each category include
both the category-level moderators and the archive-level moderators
(``subject_class == ''``), apply opt-out filters, and de-duplicate by email.
"""

from typing import Iterable, List, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session as SQLAlchemySession

from submit_ce import domain
from . import models


def split_category(category: str) -> Tuple[str, str]:
    """Split a category id into ``(archive, subject_class)``.

    ``'math.AG'`` -> ``('math', 'AG')``; ``'hep-th'`` -> ``('hep-th', '')``.
    Mirrors the way the classic ``category`` column is decomposed.
    """
    archive, _, subject_class = category.partition('.')
    return archive, subject_class


def moderators_for_categories(
        session: SQLAlchemySession,
        categories: Iterable[str],
        *,
        exclude_no_web_email: bool = True,
        exclude_no_email: bool = False,
        exclude_no_reply_to: bool = False,
) -> List[domain.Moderator]:
    """Resolve categories to the moderators that should be notified.

    For each category, both category-level moderators
    (``archive == A and subject_class == S``) and archive-level moderators
    (``archive == A and subject_class == ''``) are included. The opt-out filters
    drop moderators who have set the corresponding flag; the default mirrors
    legacy proposal emails, which exclude ``no_web_email`` moderators.

    Returns moderators de-duplicated by email and sorted by email.
    """
    # Gather the distinct (archive, subject_class) pairs to look up: the
    # category itself and its archive-level entry.
    pairs = set()
    for category in categories:
        archive, subject_class = split_category(category)
        pairs.add((archive, subject_class))
        pairs.add((archive, ''))

    if not pairs:
        return []

    conditions = [
        and_(models.Moderator.archive == archive,
             models.Moderator.subject_class == subject_class)
        for archive, subject_class in pairs
    ]
    rows = session.query(models.Moderator).filter(or_(*conditions)).all()

    by_email: dict[str, domain.Moderator] = {}
    for row in rows:
        if exclude_no_web_email and row.no_web_email:
            continue
        if exclude_no_email and row.no_email:
            continue
        if exclude_no_reply_to and row.no_reply_to:
            continue
        email = row.user.email if row.user else None
        if not email or email in by_email:
            continue
        proposer = row.user
        name = None
        if proposer is not None:
            name = f"{proposer.first_name or ''} {proposer.last_name or ''}".strip() \
                or None
        by_email[email] = domain.Moderator(
            user_id=str(row.user_id),
            email=email,
            archive=row.archive,
            subject_class=row.subject_class or '',
            name=name,
            no_email=bool(row.no_email),
            no_web_email=bool(row.no_web_email),
            no_reply_to=bool(row.no_reply_to),
        )

    return [by_email[email] for email in sorted(by_email)]


def moderator_emails(
        session: SQLAlchemySession,
        categories: Iterable[str],
        **kwargs: bool,
) -> List[str]:
    """Sorted, de-duplicated moderator email addresses for the categories."""
    return [m.email for m in
            moderators_for_categories(session, categories, **kwargs)]
