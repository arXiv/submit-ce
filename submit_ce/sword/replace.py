"""Resolving what a ``PUT`` is trying to replace.

Ports the identifier ladder in ``action_put`` (``AtomPP.pm:413-472``). A depositor
PUTs a wrapper to the ``rel="edit"`` href from an earlier deposit, or directly to a
paper id (``submit_sword.md:777-781``):

    PUT /sword-app/edit/09031234.atom     -> resolved via arXiv_tracking
    PUT /sword-app/edit/0708.0123         -> a paper id, used as-is
    PUT /sword-app/edit/cond-mat/9904123  -> an old-style paper id

Replacement is only for **announced** papers, and only by a registered paper owner
(``submit_sword.md:724-727,781``).
"""

import logging
import re
from typing import List, Optional

import arxiv.db.models as models
from sqlalchemy.orm import Session as SqlalchemySession

from submit_ce.sword.errors import SwordFault

logger = logging.getLogger(__name__)

DEPOSIT_ATOM = re.compile(r"^(\d{8})\.atom$")
"""An ``edit`` href from a previous deposit response (``AtomPP.pm:432``).

Exactly eight digits, unlike the ``rel="related"`` pattern which allows more
(``AtomPP.pm:1102``) -- so a deposit id that has grown past eight digits cannot be
resolved this way. Legacy's inconsistency, reproduced.
"""

PAPER_ID = re.compile(r"^(\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})(?:v\d+)?$")
"""New-style ``YYMM.NNNNN`` or old-style ``archive/YYMMNNN``, version optional.

``AtomPP.pm:442``. The version suffix is stripped: a replacement always creates the
next version, never targets an existing one.
"""

PENDING = re.compile(r"^submit/\d{7}")
"""A deposit still in the workflow, which cannot be replaced (``AtomPP.pm:444``)."""


def resolve_target(session: SqlalchemySession, raw: str) -> str:
    """Turn the ``/edit/`` path segment into a paper id.

    Raises `SwordFault`:

    * ENOID when there is nothing to resolve;
    * EPSUB when it names a deposit still in the workflow -- a paper has to be
      announced before it can be replaced;
    * ENVID when it is neither a resolvable deposit nor a paper id.
    """
    if not raw:
        raise SwordFault("ENOID")

    target = raw
    match = DEPOSIT_ATOM.match(raw)
    if match:
        tracking = session.query(models.Tracking).filter_by(
            sword_id=int(match.group(1))).one_or_none()
        if tracking is None:
            raise SwordFault("ENVID", raw)
        target = tracking.paper_id or ""

    if PENDING.match(target):
        raise SwordFault(
            "EPSUB",
            f"'{target}' specifies a pending submission, these cannot be replaced")

    paper = PAPER_ID.match(target)
    if not paper:
        raise SwordFault("ENVID", f"-- '{target}'")
    # Strip any version suffix: the replacement becomes the next version.
    return paper.group(1)


def paper_owners(session: SqlalchemySession, paper_id: str) -> List[str]:
    """Nicknames registered as owners of a paper.

    ``AtomPP.pm:457-465`` joins ``arXiv_paper_owners`` to ``tapir_nicknames`` via
    ``arXiv_documents``. Ownership is claimed with the paper password
    (``submit_sword.md:781``), which is outside SWORD.
    """
    document = session.query(models.Document).filter_by(
        paper_id=paper_id).one_or_none()
    if document is None:
        return []

    owner_ids = [row.user_id for row in session.query(models.PaperOwner)
                 .filter_by(document_id=document.document_id)]
    if not owner_ids:
        return []

    return [row.nickname for row in session.query(models.TapirNickname)
            .filter(models.TapirNickname.user_id.in_(owner_ids))]


def require_owner(session: SqlalchemySession, paper_id: str,
                  nickname: str) -> None:
    """Refuse a replacement by anyone who is not a registered owner.

    Case-sensitive, as the manual states explicitly
    (``submit_sword.md:726-727``).
    """
    if nickname not in paper_owners(session, paper_id):
        raise SwordFault("ENOWN")


def announced_submission_id(session: SqlalchemySession,
                            paper_id: str) -> Optional[int]:
    """The submission row that produced a paper, if there is one.

    Needed because a replacement is a new *version* of that submission
    (`CreateSubmissionVersion`), not a fresh one.
    """
    row = session.query(models.Submission).filter_by(
        doc_paper_id=paper_id).order_by(
            models.Submission.submission_id.desc()).first()
    return row.submission_id if row is not None else None


def existing_categories(session: SqlalchemySession,
                        paper_id: str) -> List[str]:
    """Categories currently on a paper, for the ERCTS match check.

    A replacement may carry no categories at all, or a set matching what is already
    there -- classification cannot change during a replacement
    (``submit_sword.md:780``).
    """
    submission_id = announced_submission_id(session, paper_id)
    if submission_id is None:
        return []
    return [row.category for row in session.query(models.SubmissionCategory)
            .filter_by(submission_id=submission_id)]
