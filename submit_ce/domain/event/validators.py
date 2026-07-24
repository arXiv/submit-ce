"""Reusable validators for events."""

import re

from arxiv.taxonomy.definitions import CATEGORIES
from qa.checks.models import Disposition, Result

from .base import Event
from ..submission import Submission
from ..exceptions import InvalidEvent


def passes_qa_checks(event: Event, check_result: Result | None) -> None:
    """
    Verify that the input passes quality assurance checks.

    Parameters
    ----------
    event : :class:`.Event`
    check_result : :class:`qa.checks.models.Result`

    Raises
    ------
    :class:`.InvalidEvent`
        Raised if `Result` is present and includes `Disposition.REJECT`.

    """
    if check_result and check_result.disposition == Disposition.REJECT:
        raise InvalidEvent(event, check_result.message)


def submission_is_not_finalized(event: Event, submission: Submission) -> None:
    """
    Verify that the submission is not finalized.

    Parameters
    ----------
    event : :class:`.Event`
    submission : :class:`.domain.submission.Submission`

    Raises
    ------
    :class:`.InvalidEvent`
        Raised if the submission is finalized.

    """
    if submission.is_finalized:
        raise InvalidEvent(event, "Cannot apply to a finalized submission")


def no_trailing_period(event: Event, submission: Submission,
                       value: str) -> None:
    """
    Verify that there are no trailing periods in ``value`` except ellipses.
    """
    if re.search(r"(?<!\.\.)\.$", value):
        raise InvalidEvent(event, "Must not contain trailing periods except"
                                  " ellipses.")


def must_be_an_active_category(event: Event, category: str,
                               submission: Submission) -> None:
    """Valid arXiv categories are defined in :mod:`arxiv.taxonomy`."""
    if not category or category not in CATEGORIES or not CATEGORIES[category].is_active:
        raise InvalidEvent(event, "Not a valid category")


def cannot_be_primary(event: Event, category: str, submission: Submission) \
        -> None:
    """The category can't already be set as a primary classification."""
    if submission.primary_classification is None:
        return
    if category == submission.primary_classification.category:
        raise InvalidEvent(event, "The same category cannot be used as both"
                                  " the primary and a secondary category.")


def cannot_be_secondary(event: Event, category: str, submission: Submission) \
        -> None:
    """The same category cannot be added as a secondary twice."""
    if category in submission.secondary_categories:
        raise InvalidEvent(event, f"Secondary {category} already set on this"
                           f" submission.")


def no_active_requests(event: Event, submission: Submission) -> None:
    """Must not have active requests"""
    if submission.has_active_requests:
        raise InvalidEvent(event, "Must not have active requests.")


def cannot_be_genph(event: Event, category: str, submission: Submission)\
        -> None:
    "Cannot be physics.gen-ph."
    if category and category == 'physics.gen-ph':
        raise InvalidEvent(event, "Cannot be physics.gen-ph.")


def no_redundant_general_category(event: Event,
                                  category: str,
                                  submission: Submission) -> None:
    """Prevents adding a general category when another category in
    that archive is already represented."""
    if CATEGORIES[category].is_general:
        if((submission.primary_classification and
                CATEGORIES[category].in_archive ==
                CATEGORIES[submission.primary_category].in_archive)
           or
           (CATEGORIES[category].in_archive
            in [CATEGORIES[cat].in_archive for
                cat in submission.secondary_categories])):
            raise InvalidEvent(event,
                               f"Cannot add general category {category}"
                               f" due to more specific category from"
                               f" {CATEGORIES[category].in_archive}.")


def no_redundant_non_general_category(event: Event,
                                      category: str,
                                      submission: Submission) -> None:
    """Prevents adding a category when a general category in that archive
    is already represented."""
    if not CATEGORIES[category].is_general:
        e_archive = CATEGORIES[category].in_archive
        if(submission.primary_classification and
           e_archive ==
           CATEGORIES[submission.primary_category].in_archive
           and CATEGORIES[submission.primary_category].is_general):
            raise InvalidEvent(event,
                               f'Cannot add more specific {category} due'
                               f' to general primary.')

        sec_archs = [tcat.in_archive for tcat in
                     [CATEGORIES[cat]
                      for cat in submission.secondary_categories]
                     if tcat.is_general]
        if e_archive in sec_archs:
            raise InvalidEvent(event,
                               f'Cannot add more spcific {category} due'
                               f' to general secondaries.')


def no_secondaries_on_general_primary(event: Event,
                                      submission: Submission) -> None:
    """A submission with a general primary category may not carry any
    secondary classifications (SUBMISSION-158).

    Checked at finalize. Unlike :func:`no_redundant_non_general_category`
    (add-time, same-archive only), this rejects *any* secondary under a
    general primary.

    Only enforced for first-version (new) submissions. Replacements
    (``version > 1``) are exempt: the replacement workflow has no
    classification stage and the primary is locked once announced
    (see ``SetPrimaryClassification._must_be_unannounced``), so every category
    on a replacement is inherited from the announced version. A general
    primary with secondaries there was grandfathered in and must not block the
    replacement (SUBMISSION-158 edge case 1).

    TODO(SUBMISSION-158 edge case 2): a moderator/EUST-added secondary on the
    *working* version still can't be distinguished from a submitter-added one
    without classification provenance, which does not exist yet.
    """
    if submission.version > 1:
        return
    if (submission.primary_classification
            and CATEGORIES[submission.primary_category].is_general
            and submission.secondary_classification):
        raise InvalidEvent(
            event,
            "A submission with a general primary category "
            f"({submission.primary_category}) may not have secondary "
            "categories.")


def no_secondary_when_primary_general(event: Event,
                                      submission: Submission) -> None:
    """A cross-list (secondary) may not be *added* when the primary category
    is general (SUBMISSION-158).

    Unlike :func:`no_secondaries_on_general_primary`, which looks at
    secondaries already present, this rejects the add itself based only on the
    primary. It is used by :class:`.AddSecondaryClassification` so that even
    the first secondary under a general primary is blocked (the event runs
    before its own projection, so the secondary being added is not yet on the
    submission).

    Replacements (``version > 1``) are exempt for the same reason as
    :func:`no_secondaries_on_general_primary`.
    """
    if submission.version > 1:
        return
    if (submission.primary_classification
            and CATEGORIES[submission.primary_category].is_general):
        raise InvalidEvent(
            event,
            "A cross-list category may not be added when the primary "
            f"category ({submission.primary_category}) is general.")


def max_secondaries(event: Event, submission: Submission) -> None:
    "No more than 4 secondary categories per submission."
    if (submission.secondary_classification and
            len(submission.secondary_classification) + 1 > 4):
        raise InvalidEvent(
            event, "No more than 4 secondary categories per submission.")
