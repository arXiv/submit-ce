"""
Data structures for submissions events.

TODO update this documentation, it is from NG and is stale

- Events have unique identifiers generated from their data (creation, agent, submission).
- Events provide methods to update a `Submission` based on the event data.
- Events provide validation methods for event data.

Writing new events/commands
===========================

Events/commands are implemented as classes that inherit from :class:`.Event`.
It should:

- Define associated data.
- Implement a validation method with the signature
  ``validate(self, submission: Submission) -> None`` (see below).
- Implement a projection method with the signature
  ``project(self, submission: Submission) -> Submission:`` that mutates
  the passed :class:`.domain.submission.Submission` instance.
  The projection *must not* generate side effects, because it will be called
  any time we are generating the state of a submission.
- Be fully documented. Be sure that the class docstring fully describes the
  meaning of the event/command, and that both public and private methods have
  at least a summary docstring.
- Have a corresponding :class:`unittest.TestCase` in :mod:`arxiv.submission.domain.tests.test_events`.

Adding validation to events
===========================

Each command/event class should implement an instance method
``validate(self, submission: Submission) -> None`` that raises
:class:`.InvalidEvent` exceptions if the data on the event instance is not
valid.

For clarity, it's a good practice to individuate validation steps as separate
private instance methods, and call them from the public ``validate`` method.
This makes it easier to identify which validation criteria are being applied,
in what order, and what those criteria mean.

See :class:`.SetPrimaryClassification` for an example.

We could consider standalone validation functions for validation checks that
are performed on several event types (instead of just private instance
methods).
"""


import copy
import re
from dataclasses import field
from datetime import datetime
from typing import Optional, List, Union, ClassVar

from arxiv.license import LICENSES
from arxiv.metadata import metacheck
import bleach
from arxiv.taxonomy.definitions import CATEGORIES
from pytz import UTC

from . import validators
from .base import Event
from .base import event_factory as make_event
from .email import EmailSubmitterFinalizeMsg
from .file import UploadFiles, RemoveFiles, RemoveAllFiles
from .flag import AddMetadataFlag, AddUserFlag, AddContentFlag, RemoveFlag, \
    AddHold, RemoveHold
from .request import RequestCrossList, RequestWithdrawal, ApplyRequest, \
    RejectRequest, ApproveRequest, CancelRequest
from ..agent import System
from ..annotation import Feature, ClassifierResults, \
    ClassifierResult
from ..preview import Preview
from ..submission import Submission, Author, \
    Classification, License, Hold
from ..uploads import SourceFormat
from ..exceptions import InvalidEvent


__all__ = [
    make_event,
    validators,
    Event,
    UploadFiles, RemoveFiles, RemoveAllFiles,
    AddMetadataFlag, AddUserFlag, AddContentFlag, RemoveFlag,
    AddHold, RemoveHold,
    RequestCrossList, RequestWithdrawal, ApplyRequest,
    RejectRequest, ApproveRequest, CancelRequest,
    System,
    Feature, ClassifierResults,
    ClassifierResult,
    Preview,
    Submission, Author,
    Classification, License
]

import logging
logger = logging.getLogger(__name__)


# BDC: I was thinking of doing a validator on the type but this conflicted with some
# test code that expected to get an InvalidEvent exception. It seems wrong to set this to raise
# that since it might be used outside an Event
#ActiveCategory = Annotated[str, AfterValidator(is_active_category)]

ActiveCategory = str
"""Type for an active category."""

#Category = Annotated[str, AfterValidator(is_category)]
Category = str
"""Type for a category active or inactive."""



class CreateSubmission(Event):
    """Creation of a new :class:`.domain.submission.Submission`."""

    NAME = "create submission"
    NAMED = "submission created"

    # This is the one event that deviates from the base Event class in not
    # requiring/accepting a submission on which to operate. Python/mypy still
    # has a little way to go in terms of supporting this kind of inheritance
    # scenario. For reference, see:
    # - https://github.com/python/typing/issues/269
    # - https://github.com/python/mypy/issues/5146
    # - https://github.com/python/typing/issues/241
    def validate_pre_lock(self, submission: None = None) -> None:   # type: ignore
        """Validate creation of a submission."""
        return

    def project(self, submission: None = None) -> Submission:   # type: ignore
        """Create a new :class:`.domain.submission.Submission`."""
        return Submission(creator=self.creator, created=self.created,
                          owner=self.creator, proxy=self.proxy,
                          client=self.client)


class CreateSubmissionVersion(Event):
    """Creates a new version of a submission.

    The user or client may make additional changes before finalizing the
    submission.

    """

    NAME = "create a new version"
    NAMED = "new version created"

    def validate_pre_lock(self, submission: Submission) -> None:
        """Only applies to announced submissions."""
        if not submission.is_announced:
            raise InvalidEvent(self, "Must already be announced")
        validators.no_active_requests(self, submission)

    def project(self, submission: Submission) -> Submission:
        """Increment the version number, and reset several fields."""
        submission.version += 1
        submission.status = Submission.WORKING
        # Return these to default.
        submission.status = Submission.status
        submission.source_format = Submission.source_format
        submission.uncompressed_size = Submission.uncompressed_size
        submission.license = Submission.license
        submission.submitter_is_author = Submission.submitter_is_author
        submission.submitter_contact_verified = \
            Submission.submitter_contact_verified
        submission.submitter_accepts_policy = \
            Submission.submitter_accepts_policy
        submission.submitter_confirmed_preview = \
            Submission.submitter_confirmed_preview
        return submission


class Rollback(Event):
    """Roll back to the most recent announced version, or delete."""

    NAME = "roll back or delete"
    NAMED = "rolled back or deleted"

    def validate_pre_lock(self, submission: Submission) -> None:
        """Only applies to submissions in an unannounced state."""
        if submission.is_announced:
            raise InvalidEvent(self, "Cannot already be announced")
        elif submission.version > 1 and not submission.versions:
            raise InvalidEvent(self, "No announced version to which to revert")

    def project(self, submission: Submission) -> Submission:
        """Decrement the version number, and reset fields."""
        if submission.version == 1:
            submission.status = Submission.DELETED
            return submission
        submission.version -= 1
        target = submission.versions[-1]
        # Return these to last announced state.
        submission.status = target.status
        submission.source_format = target.source_format
        submission.uncompressed_size = target.uncompressed_size
        submission.submitter_contact_verified = \
            target.submitter_contact_verified
        submission.submitter_accepts_policy = \
            target.submitter_accepts_policy
        submission.submitter_confirmed_preview = \
            target.submitter_confirmed_preview
        submission.license = target.license
        submission.metadata = copy.deepcopy(target.metadata)
        return submission


class ConfirmContactInformation(Event):
    """Submitter has verified their contact information."""

    NAME = "confirm contact information"
    NAMED = "contact information confirmed"

    def validate_pre_lock(self, submission: Submission) -> None:
        """Cannot apply to a finalized submission."""
        validators.submission_is_not_finalized(self, submission)

    def project(self, submission: Submission) -> Submission:
        """Update :attr:`.Submission.submitter_contact_verified`."""
        submission.submitter_contact_verified = True
        return submission


class SetProxyInformation(Event):
    """Set proxy information."""
    proxied_name: str
    proxied_email: str
    proxy_name: str

    def apply(self, submission: Submission) -> Submission:
        # We need to use the Creator dataclass. This holds
        # submitter_name and submitter_email (from legacy).
        # Proxy name setting indicates that these fields are
        # set by submitter and may not correspond to
        # user_id (2.0) or submitter_id (1.5).
        submission.creator.name = self.proxied_name
        submission.creator.email = self.proxied_email
        submission.proxy = self.proxy_name
        return submission


class ConfirmAuthorship(Event):
    """The submitting user asserts whether they are an author of the paper."""

    NAME = "confirm that submitter is an author"
    NAMED = "submitter authorship status confirmed"

    submitter_is_author: bool = True

    def validate_pre_lock(self, submission: Submission) -> None:
        """Cannot apply to a finalized submission."""
        validators.submission_is_not_finalized(self, submission)

    def project(self, submission: Submission) -> Submission:
        """Update the authorship flag on the submission."""
        submission.submitter_is_author = self.submitter_is_author
        return submission


class ConfirmPolicy(Event):
    """The submitting user accepts the arXiv submission policy."""

    NAME = "confirm policy acceptance"
    NAMED = "policy acceptance confirmed"
    agreement_id: int
    
    def validate_pre_lock(self, submission: Submission) -> None:
        """Cannot apply to a finalized submission."""
        validators.submission_is_not_finalized(self, submission)

    def project(self, submission: Submission) -> Submission:
        """Set the policy flag on the submission."""
        submission.submitter_accepts_policy = True
        submission.agreement_id = self.agreement_id
        return submission


class SetPrimaryClassification(Event):
    """Update the primary classification of a submission."""

    NAME = "set primary classification"
    NAMED = "primary classification set"

    category: Optional[ActiveCategory] = None

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the primary classification category."""
        if self.category is None:
            raise InvalidEvent(self, "Must have a category")
        validators.must_be_an_active_category(self, self.category, submission)
        self._creator_must_be_endorsed(submission)
        self._must_be_unannounced(submission)
        validators.submission_is_not_finalized(self, submission)
        validators.cannot_be_secondary(self, self.category, submission)

    def _must_be_unannounced(self, submission: Submission) -> None:
        """Can only be set on the first version before publication."""
        if submission.arxiv_id is not None or submission.version > 1:
            raise InvalidEvent(self, "Can only be set on the first version,"
                                     " before publication.")

    def _creator_must_be_endorsed(self, submission: Submission) -> None:
        """Creator of this event must be endorsed for the category."""
        if isinstance(self.creator, System):
            return
        try:
            #archive = taxonomy.CATEGORIES[self.category]['in_archive']
            archive = CATEGORIES[self.category].in_archive
        except KeyError:
            archive = self.category
        if self.category not in self.creator.endorsements \
                and f'{archive}.*' not in self.creator.endorsements \
                and '*.*' not in self.creator.endorsements:
            raise InvalidEvent(self, f"Creator is not endorsed for"
                                     f" {self.category}.")

    def project(self, submission: Submission) -> Submission:
        """Set :attr:`.domain.Submission.primary_classification`."""
        assert self.category is not None
        clsn = Classification(category=self.category)
        submission.primary_classification = clsn
        return submission


class AddSecondaryClassification(Event):
    """Add a secondary :class:`.Classification` to a submission."""

    NAME = "add cross-list classification"
    NAMED = "cross-list classification added"

    #category: Optional[taxonomy.Category] = field(default=None)
    category: Optional[ActiveCategory] = None

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the secondary classification category to add."""
        assert self.category is not None
        validators.must_be_an_active_category(self, self.category, submission)
        validators.cannot_be_primary(self, self.category, submission)
        validators.cannot_be_secondary(self, self.category, submission)
        validators.max_secondaries(self, submission)
        validators.no_redundant_general_category(self, self.category, submission)
        validators.no_redundant_non_general_category(self, self.category, submission)
        validators.cannot_be_genph(self, self.category, submission)

    def project(self, submission: Submission) -> Submission:
        """Add a :class:`.Classification` as a secondary classification."""
        assert self.category is not None
        classification = Classification(category=self.category)
        submission.secondary_classification.append(classification)
        return submission


class RemoveSecondaryClassification(Event):
    """Remove secondary :class:`.Classification` from submission."""

    NAME = "remove cross-list classification"
    NAMED = "cross-list classification removed"

    category: Optional[str] = field(default=None)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the secondary classification category to remove."""
        assert self.category is not None
        validators.must_be_an_active_category(self, self.category, submission)
        self._must_already_be_present(submission)
        validators.submission_is_not_finalized(self, submission)

    def project(self, submission: Submission) -> Submission:
        """Remove from :attr:`.Submission.secondary_classification`."""
        assert self.category is not None
        submission.secondary_classification = [
            classn for classn in submission.secondary_classification
            if not classn.category == self.category
        ]
        return submission

    def _must_already_be_present(self, submission: Submission) -> None:
        """One cannot remove a secondary that is not actually set."""
        if self.category not in submission.secondary_categories:
            raise InvalidEvent(self, 'No such category on submission')


class SetLicense(Event):
    """The submitter has selected a license for their submission."""

    NAME = "select distribution license"
    NAMED = "distribution license selected"

    license_name: Optional[str] = field(default=None)
    license_uri: Optional[str] = field(default=None)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the selected license."""
        validators.submission_is_not_finalized(self, submission)
        if not self.license_uri:
            raise InvalidEvent(self, "License must have a URL")
        if self.license_uri not in LICENSES:
            raise InvalidEvent(self, "License URL is not on the list of valid licenses")
        if self.license_uri not in [uri for uri, license in LICENSES.items() if license["is_current"]]:
            raise InvalidEvent(self, "License URL is not on the current list of valid licenses")

    def project(self, submission: Submission) -> Submission:
        """Set :attr:`.domain.Submission.license`."""
        assert self.license_uri is not None
        submission.license = License(name=self.license_name,
                                     uri=self.license_uri)
        return submission


class SetTitle(Event):
    """Update the title of a submission."""

    NAME = "update title"
    NAMED = "title updated"

    title: str = field(default='')

    MIN_LENGTH: ClassVar[str] = 5
    MAX_LENGTH: ClassVar[int] = 240
    ALLOWED_HTML: ClassVar[List[str]] = ["br", "sup", "sub", "hr", "em", "strong", "h"]

    def model_post_init(self, *args, **kwargs) -> None:
        """Perform some light cleanup on the provided value."""
        self.title = self.cleanup(self.title)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the title value."""
        validators.submission_is_not_finalized(self, submission)
        check = metacheck.check_title(self.title)
        if check and check.disposition != metacheck.OK:
            raise InvalidEvent(self, "", check)
        self._does_not_contain_html_escapes(submission)
        validators.no_trailing_period(self, submission, self.title)
        self._check_for_html(submission)

    def project(self, submission: Submission) -> Submission:
        """Update the title on a :class:`.domain.submission.Submission`."""
        submission.metadata.title = self.title
        return submission

    def _does_not_contain_html_escapes(self, submission: Submission) -> None:
        """The title must not contain HTML escapes."""
        if re.search(r"\&(?:[a-z]{3,4}|#x?[0-9a-f]{1,4})\;", self.title):
            raise InvalidEvent(self, "Title may not contain HTML escapes")

    def _acceptable_length(self, submission: Submission) -> None:
        """Verify that the title is an acceptable length."""
        N = len(self.title)
        if N < self.MIN_LENGTH or N > self.MAX_LENGTH:
            raise InvalidEvent(self, f"Title must be between {self.MIN_LENGTH}"
                                     f" and {self.MAX_LENGTH} characters")

    # In classic, this is only an admin post-hoc check.
    def _check_for_html(self, submission: Submission) -> None:
        """Check for disallowed HTML."""
        N = len(self.title)
        N_after = len(bleach.clean(self.title, tags=self.ALLOWED_HTML,
                                   strip=True))
        if N > N_after:
            raise InvalidEvent(self, "Title contains unacceptable HTML tags")

    @staticmethod
    def cleanup(value: str) -> str:
        """Perform some light tidying on the title."""
        value = re.sub(r"\s+", " ", value).strip()       # Single spaces only.
        return value


class SetAbstract(Event):
    """Update the abstract of a submission."""

    NAME = "update abstract"
    NAMED = "abstract updated"

    abstract: str = field(default='')

    MIN_LENGTH: ClassVar[int] = 20
    MAX_LENGTH: ClassVar[int] = 1920

    def model_post_init(self, *args) -> None:
        """Perform some light cleanup on the provided value."""
        #super(SetAbstract, self).__post_init__()
        self.abstract = self.cleanup(self.abstract)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the abstract value."""
        validators.submission_is_not_finalized(self, submission)
        check = metacheck.check_abstract(self.abstract)
        if check and check.disposition != metacheck.OK:
            raise InvalidEvent(self, "", check)

    def project(self, submission: Submission) -> Submission:
        """Update the abstract on a :class:`.domain.submission.Submission`."""
        submission.metadata.abstract = self.abstract
        return submission

    def _acceptable_length(self) -> None:
        N = len(self.abstract)
        if N < self.MIN_LENGTH or N > self.MAX_LENGTH:
            raise InvalidEvent(self,
                               f"Abstract must be between {self.MIN_LENGTH}"
                               f" and {self.MAX_LENGTH} characters. Was {len(self.abstract)}")

    @staticmethod
    def cleanup(value: str) -> str:
        """Perform some light tidying on the abstract."""
        value = value.strip()   # Remove leading or trailing spaces
        # Tidy paragraphs which should be indicated with "\n  ".
        value = re.sub(r"[ ]+\n", "\n", value)
        value = re.sub(r"\n\s+", "\n  ", value)
        # Newline with no following space is removed, so treated as just a
        # space in paragraph.
        value = re.sub(r"(\S)\n(\S)", "\\g<1> \\g<2>", value)
        # Tab->space, multiple spaces->space.
        value = re.sub(r"\t", " ", value)
        value = re.sub(r"(?<!\n)[ ]{2,}", " ", value)
        # Remove tex return (\\) at end of line or end of abstract.
        value = re.sub(r"\s*\\\\(\n|$)", "\\g<1>", value)
        # Remove lone period.
        value = re.sub(r"\n\.\n", "\n", value)
        value = re.sub(r"\n\.$", "", value)
        return value


class SetDOI(Event):
    """Update the external DOI of a submission."""

    NAME = "add a DOI"
    NAMED = "DOI added"

    doi: str = field(default='')

    def model_post_init(self, *args, **kwargs) -> None:
        """Perform some light cleanup on the provided value."""
        self.doi = self.cleanup(self.doi)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the DOI value."""
        if submission.status == Submission.SUBMITTED \
                and not submission.is_announced:
            raise InvalidEvent(self, 'Cannot edit a finalized submission')
        if not self.doi:    # Can be blank.
            return
        check = metacheck.check_doi(self.doi)
        if check and check.disposition != metacheck.OK:
            raise InvalidEvent(self, "", check)

    def project(self, submission: Submission) -> Submission:
        """Update the doi on a :class:`.domain.submission.Submission`."""
        submission.metadata.doi = self.doi
        return submission

    def _valid_doi(self, value: str) -> bool:
        if re.match(r"^10\.\d{4,5}\/\S+$", value):
            return True
        return False

    @staticmethod
    def cleanup(value: str) -> str:
        """Perform some light tidying on the title."""
        value = re.sub(r"\s+", " ", value).strip()        # Single spaces only.
        return value


class SetMSCClassification(Event):
    """Update the MSC classification codes of a submission."""

    NAME = "update MSC classification"
    NAMED = "MSC classification updated"

    msc_class: str = field(default='')

    MAX_LENGTH: ClassVar[int] = 160

    def model_post_init(self, *args, **kwargs) -> None:
        """Perform some light cleanup on the provided value."""
        self.msc_class = self.cleanup(self.msc_class)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the MSC classification value."""
        validators.submission_is_not_finalized(self, submission)
        if not self.msc_class:    # Blank values are OK.
            return
        check = metacheck.check_msc_class(self.msc_class)
        if check and check.disposition != metacheck.OK:
            raise InvalidEvent(self, "", check)

    def project(self, submission: Submission) -> Submission:
        """Update the MSC classification on a :class:`.domain.submission.Submission`."""
        submission.metadata.msc_class = self.msc_class
        return submission

    @staticmethod
    def cleanup(value: str) -> str:
        """Perform some light fixes on the MSC classification value."""
        value = re.sub(r"\s+", " ", value).strip()
        value = re.sub(r"\s*\.[\s.]*$", "", value)
        value = value.replace(";", ",")     # No semicolons, should be comma.
        value = re.sub(r"\s*,\s*", ", ", value)     # Want: comma, space.
        value = re.sub(r"^MSC([\s:\-]{0,4}(classification|class|number))?"
                       r"([\s:\-]{0,4}\(?2000\)?)?[\s:\-]*",
                       "", value, flags=re.I)
        return value


class SetACMClassification(Event):
    """Update the ACM classification codes of a submission."""

    NAME = "update ACM classification"
    NAMED = "ACM classification updated"

    acm_class: str = field(default='')
    """E.g. F.2.2; I.2.7"""

    MAX_LENGTH: ClassVar[int] = 160

    def model_post_init(self, *args, **kwargs) -> None:
        """Perform some light cleanup on the provided value."""
        self.acm_class = self.cleanup(self.acm_class)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the ACM classification value."""
        validators.submission_is_not_finalized(self, submission)
        if not self.acm_class:    # Blank values are OK.
            return
        check = metacheck.check_acm_class(self.acm_class)
        if check and check.disposition != metacheck.OK:
            raise InvalidEvent(self, "", check)

    def project(self, submission: Submission) -> Submission:
        """Update the ACM classification on a :class:`.domain.submission.Submission`."""
        submission.metadata.acm_class = self.acm_class
        return submission

    def _valid_acm_class(self, submission: Submission) -> None:
        """Check that the value is a valid ACM class."""
        ptn = r"^[A-K]\.[0-9m](\.(\d{1,2}|m)(\.[a-o])?)?$"
        for acm_class in self.acm_class.split(';'):
            if not re.match(ptn, acm_class.strip()):
                raise InvalidEvent(self, f"Not a valid ACM class: {acm_class}")

    @staticmethod
    def cleanup(value: str) -> str:
        """Perform light cleanup."""
        value = re.sub(r"\s+", " ", value).strip()
        value = re.sub(r"\s*\.[\s.]*$", "", value)
        value = re.sub(r"^ACM-class:\s+", "", value, flags=re.I)
        value = value.replace(",", ";")
        _value = []
        for v in value.split(';'):
            v = v.strip().upper().rstrip('.')
            v = re.sub(r"^([A-K])(\d)", "\\g<1>.\\g<2>", v)
            v = re.sub(r"M$", "m", v)
            _value.append(v)
        value = "; ".join(_value)
        return value


class SetJournalReference(Event):
    """Update the journal reference of a submission."""

    NAME = "add a journal reference"
    NAMED = "journal reference added"

    journal_ref: str = field(default='')

    def model_post_init(self, *args, **kwargs) -> None:
        """Perform some light cleanup on the provided value."""
        self.journal_ref = self.cleanup(self.journal_ref)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the journal reference value."""
        if not self.journal_ref:    # Blank values are OK.
            return
        check = metacheck.check_journal_ref(self.journal_ref)
        if check and check.disposition != metacheck.OK:
            raise InvalidEvent(self, "", check)

    def project(self, submission: Submission) -> Submission:
        """Update the journal reference on a :class:`.domain.submission.Submission`."""
        submission.metadata.journal_ref = self.journal_ref
        return submission

    def _no_disallowed_words(self, submission: Submission) -> None:
        """Certain words are not permitted."""
        for word in ['submit', 'in press', 'appear', 'accept', 'to be publ']:
            if word in self.journal_ref.lower():
                raise InvalidEvent(self,
                                   f"The word '{word}' should appear in the"
                                   f" comments, not the Journal ref")

    def _contains_valid_year(self, submission: Submission) -> None:
        """Must contain a valid year."""
        if not re.search(r"(\A|\D)(19|20)\d\d(\D|\Z)", self.journal_ref):
            raise InvalidEvent(self, "Journal reference must include a year")

    @staticmethod
    def cleanup(value: str) -> str:
        """Perform light cleanup."""
        value = value.replace('PHYSICAL REVIEW LETTERS',
                              'Physical Review Letters')
        value = value.replace('PHYSICAL REVIEW', 'Physical Review')
        value = value.replace('OPTICS LETTERS', 'Optics Letters')
        return value


class SetReportNumber(Event):
    """Update the report number of a submission."""

    NAME = "update report number"
    NAMED = "report number updated"

    report_num: str = field(default='')

    def model_post_init(self, *args, **kwargs) -> None:
        """Perform some light cleanup on the provided value."""
        self.report_num = self.cleanup(self.report_num)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the report number value."""
        if not self.report_num:    # Blank values are OK.
            return
        check = metacheck.check_report_num(self.report_num)
        if check and check.disposition != metacheck.OK:
            raise InvalidEvent(self, "", check)

    def project(self, submission: Submission) -> Submission:
        """Set report number on a :class:`.domain.submission.Submission`."""
        submission.metadata.report_num = self.report_num
        return submission

    @staticmethod
    def cleanup(value: str) -> str:
        """Light cleanup on report number value."""
        value = re.sub(r"\s+", " ", value).strip()
        value = re.sub(r"\s*\.[\s.]*$", "", value)
        return value


class SetComments(Event):
    """Update the comments of a submission."""

    NAME = "update comments"
    NAMED = "comments updated"

    comments: str = field(default='')

    MAX_LENGTH: ClassVar[int] = 400

    def model_post_init(self, *args, **kwargs) -> None:
        """Perform some light cleanup on the provided value."""
        self.comments = self.cleanup(self.comments)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the comments value."""
        validators.submission_is_not_finalized(self, submission)
        if not self.comments:    # Blank values are OK.
            return
        check = metacheck.check_comments(self.comments)
        if check and check.disposition != metacheck.OK:
            raise InvalidEvent(self, "", check)

    def project(self, submission: Submission) -> Submission:
        """Update the comments on a :class:`.domain.submission.Submission`."""
        submission.metadata.comments = self.comments
        return submission

    @staticmethod
    def cleanup(value: str) -> str:
        """Light cleanup on comment value."""
        value = re.sub(r"\s+", " ", value).strip()
        value = re.sub(r"\s*\.[\s.]*$", "", value)
        return value


class SetAuthors(Event):
    """Update the authors on a :class:`.domain.submission.Submission`."""

    NAME = "update authors"
    NAMED = "authors updated"

    authors: List[Author] = field(default_factory=list)
    authors_display: Optional[str] = field(default=None)
    """The authors string may be provided."""

    def model_post_init(self, *args, **kwargs) -> None:
        """Autogenerate and/or clean display names."""
        self.authors = [
            Author(**a) if isinstance(a, dict) else a   # type: ignore
            for a in self.authors
        ]
        if not self.authors_display:
            self.authors_display = self._canonical_author_string()
        self.authors_display = self.cleanup(self.authors_display)

    def validate_pre_lock(self, submission: Submission) -> None:
        """May not apply to a finalized submission."""
        validators.submission_is_not_finalized(self, submission)
        check = metacheck.check_authors(self.authors_display)
        if check and check.disposition != metacheck.OK:
            raise InvalidEvent(self, "", check)

    def _canonical_author_string(self) -> str:
        """Canonical representation of authors, using display names."""
        return ", ".join([au.display for au in self.authors
                          if au.display is not None])

    @staticmethod
    def cleanup(s: str) -> str:
        """Perform some light tidying on the provided author string(s)."""
        s = re.sub(r"\s+", " ", s)          # Single spaces only.
        s = re.sub(r",(\s*,)+", ",", s)     # Remove double commas.
        # Add spaces between word and opening parenthesis.
        s = re.sub(r"(\w)\(", r"\g<1> (", s)
        # Add spaces between closing parenthesis and word.
        s = re.sub(r"\)(\w)", r") \g<1>", s)
        # Change capitalized or uppercase `And` to `and`.
        s = re.sub(r"\bA(?i:ND)\b", "and", s)
        return s.strip()   # Removing leading and trailing whitespace.

    def project(self, submission: Submission) -> Submission:
        """Replace :attr:`.Submission.metadata.authors`."""
        assert self.authors_display is not None
        submission.metadata.authors = self.authors
        submission.metadata.authors_display = self.authors_display
        return submission




class SetSourceFormat(Event):
    """Set the source format of a submission (detected from preflight)."""

    NAME = "set source format"
    NAMED = "source format set"

    source_format: Optional[str] = field(default=None)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate that source_format is a known SourceFormat value."""
        if self.source_format is None:
            return
        try:
            SourceFormat(self.source_format)
        except ValueError:
            raise InvalidEvent(self,
                               f"Unknown source format: {self.source_format}")

    def project(self, submission: Submission) -> Submission:
        """Set :attr:`.domain.Submission.source_format`."""
        if self.source_format is None:
            submission.source_format = None
        else:
            submission.source_format = SourceFormat(self.source_format)
        return submission


class ConfirmSourceProcessed(Event):
    """
    Confirm that the submission source was successfully processed.

    For TeX and PS submissions, this will involve compilation using the AutoTeX
    tree. For PDF-only submissions, this may simply involve checking that a
    PDF exists.

    If this event has occurred, it indicates that a preview of the submission
    content is available.
    """

    NAME = "confirm source has been processed"
    NAMED = "confirmed that source has been processed"

    source_id: int = field(default=-1)
    """Identifier of the source from which the preview was generated."""

    source_checksum: str = field(default='')
    """Checksum of the source from which the preview was generated."""

    preview_checksum: str = field(default='')
    """Checksum of the preview content itself."""

    size_bytes: int = field(default=-1)
    """Size (in bytes) of the preview content."""

    added: Optional[datetime] = field(default=None)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Make sure that a preview is actually provided."""
        # if self.source_id < 0:
        #     raise InvalidEvent(self, "Preview not provided")
        # if not self.source_checksum:
        #     raise InvalidEvent(self, 'Missing source checksum')
        # if not self.preview_checksum:
        #     raise InvalidEvent(self, 'Missing preview checksum')
        # if not self.size_bytes:
        #     raise InvalidEvent(self, 'Missing preview size')
        # if self.added is None:
        #     raise InvalidEvent(self, 'Missing added datetime')

    def project(self, submission: Submission) -> Submission:
        """Set :attr:`Submission.is_source_processed`."""
        submission.is_source_processed = True
        submission.preview = Preview(source_id=self.source_id,  # type: ignore
                                     source_checksum=self.source_checksum,
                                     preview_checksum=self.preview_checksum,
                                     size_bytes=self.size_bytes,
                                     added=self.added)
        return submission


class UnConfirmSourceProcessed(Event):
    """
    Unconfirm that the submission source was successfully processed.

    This can be used to mark a submission as unprocessed even though the
    source content has not changed. For example, when reprocessing a
    submission.
    """

    NAME = "unconfirm source has been processed"
    NAMED = "unconfirmed that source has been processed"

    def validate_pre_lock(self, submission: Submission) -> None:
        """Nothing to do."""

    def project(self, submission: Submission) -> Submission:
        """Set :attr:`Submission.is_source_processed`."""
        submission.is_source_processed = False
        submission.preview = None
        return submission


class ConfirmPreview(Event):
    """
    Confirm that the paper and abstract previews are acceptable.

    This event indicates that the submitter has viewed the content preview as
    well as the metadata that will be displayed on the abstract page, and
    affirms the acceptability of all content.
    """

    NAME = "approve submission preview"
    NAMED = "submission preview approved"

    preview_checksum: Optional[str] = field(default=None)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate data for :class:`.ConfirmPreview`.

        For source formats that require compilation (TeX, PostScript) the
        submission must have a separately-built preview (populated by
        :class:`.ConfirmSourceProcessed` during the Process step) and its
        checksum must match what the submitter just viewed.

        For source formats that do not require compilation (PDF, HTML)
        the source IS the preview -- no ``ConfirmSourceProcessed`` runs
        and ``submission.preview`` is legitimately ``None``. We accept
        the confirmation in that case without checking preview state.

        This mirrors the ``has_non_processing_content`` pattern in
        ``submit_ce/ui/workflow/conditions.py`` so the event-layer
        validation agrees with the workflow-layer condition that
        already lets PDF/HTML submissions pass through ``is_source_processed``.
        """
        validators.submission_is_not_finalized(self, submission)
        requires_processing = submission.source_format in (
            SourceFormat.TEX, SourceFormat.POSTSCRIPT,
        )
        if requires_processing:
            if submission.preview is None:
                raise InvalidEvent(self, "Preview not set on submission")
            if self.preview_checksum != submission.preview.preview_checksum:
                raise InvalidEvent(
                    self,
                    f"Checksum {self.preview_checksum} does not match current"
                    f" preview checksum: {submission.preview.preview_checksum}"
                )


    def project(self, submission: Submission) -> Submission:
        """Set :attr:`Submission.submitter_confirmed_preview`."""
        submission.submitter_confirmed_preview = True
        return submission


class FinalizeSubmission(Event):
    """Send the submission to the queue for announcement."""

    NAME = "finalize submission for announcement"
    NAMED = "submission finalized"

    REQUIRED: ClassVar[str] = [
        'creator', 'primary_classification',
        # TODO this is broken: 'submitter_contact_verified',
        'submitter_accepts_policy', 'license', 'source_format', 'metadata',
    ]
    REQUIRED_METADATA: ClassVar[str] = ['title', 'abstract', 'authors_display']

    CONSEQUENCE_TYPES = frozenset({AddHold, EmailSubmitterFinalizeMsg})

    def validate_pre_lock(self, submission: Submission) -> None:
        """Ensure that all required data/steps are complete."""
        if submission.is_finalized:
            raise InvalidEvent(self, "Submission already finalized")
        if not submission.is_active:
            raise InvalidEvent(self, "Submission must be active")
        self._required_fields_are_complete(submission)
        validators.no_secondaries_on_general_primary(self, submission)

    def project(self, submission: Submission) -> Submission:
        """Set :attr:`Submission.is_finalized`."""
        submission.status = Submission.SUBMITTED
        submission.submitted = datetime.now(UTC)
        return submission

    def consequences(self, submission: Submission) -> List[Event]:
        """Follow-on events when a submission is finalized.

        1. Place an oversize submission on hold. Recording a `SOURCE_OVERSIZE`
           hold (while status stays `SUBMITTED`) is what makes
           :attr:`Submission.is_on_hold` report true; there is no separate hold
           status in this model. Skipped if a waiver already exists.
        2. Send the submitter the on-submit confirmation email.
        """
        events: List[Event] = []
        if submission.is_oversize \
                and not submission.has_waiver_for(Hold.Type.SOURCE_OVERSIZE):
            events.append(AddHold(creator=System(name=__name__),
                                  submission_id=submission.submission_id,
                                  hold_type=Hold.Type.SOURCE_OVERSIZE,
                                  hold_reason="source is oversize"))
        sid = submission.submission_id
        events.append(EmailSubmitterFinalizeMsg(
            creator=System(name=__name__),
            email_to=self.creator,
            submission_id=str(sid) if sid is not None else None))
        return events

    def _required_fields_are_complete(self, submission: Submission) -> None:
        """Verify that all required fields are complete."""
        for key in self.REQUIRED:
            if not getattr(submission, key):
                raise InvalidEvent(self, f"Missing {key}")
        for key in self.REQUIRED_METADATA:
            if not getattr(submission.metadata, key):
                raise InvalidEvent(self, f"Missing {key}")


class UnFinalizeSubmission(Event):
    """Withdraw the submission from the queue for announcement."""

    NAME = "re-open submission for modification"
    NAMED = "submission re-opened for modification"

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the unfinalize action."""
        self._must_be_finalized(submission)
        if submission.is_announced:
            raise InvalidEvent(self, "Cannot unfinalize an announced paper")

    def _must_be_finalized(self, submission: Submission) -> None:
        """May only unfinalize a finalized submission."""
        if not submission.is_finalized:
            raise InvalidEvent(self, "Submission is not finalized")

    def project(self, submission: Submission) -> Submission:
        """Set :attr:`Submission.is_finalized`."""
        submission.status = Submission.WORKING
        submission.submitted = None
        return submission


class Announce(Event):
    """Announce the current version of the submission."""

    NAME = "publish submission"
    NAMED = "submission announced"

    arxiv_id: Optional[str] = None

    def validate_pre_lock(self, submission: Submission) -> None:
        """Make sure that we have a valid arXiv ID."""
        # TODO: When we're using this to perform publish in NG, we will want to
        # re-enable this step.
        #
        # if not submission.status == Submission.SUBMITTED:
        #     raise InvalidEvent(self,
        #                        "Can't publish in state %s" % submission.status)
        # if self.arxiv_id is None:
        #     raise InvalidEvent(self, "Must provide an arXiv ID.")
        # try:
        #     arxiv_identifier.parse_arxiv_id(self.arxiv_id)
        # except ValueError:
        #     raise InvalidEvent(self, "Not a valid arXiv ID.")

    def project(self, submission: Submission) -> Submission:
        """Set the arXiv ID on the submission."""
        submission.arxiv_id = self.arxiv_id
        submission.status = Submission.ANNOUNCED
        submission.versions.append(copy.deepcopy(submission))
        return submission


# Moderation-related events.


# # class CreateComment(Event):
#     """Creation of a :class:`.Comment` on a :class:`.domain.submission.Submission`."""
#
#     read_scope = 'submission:moderate'
#     write_scope = 'submission:moderate'
#
#     body: str = field(default_factory=str)
#     scope: str = 'private'
#
#     def validate_pre_lock(self, submission: Submission) -> None:
#         """The :attr:`.body` should be set."""
#         if not self.body:
#             raise ValueError('Comment body not set')
#
#     def project(self, submission: Submission) -> Submission:
#         """Create a new :class:`.Comment` and attach it to the submission."""
#         submission.comments[self.event_id] = Comment(
#             event_id=self.event_id,
#             creator=self.creator,
#             created=self.created,
#             proxy=self.proxy,
#             submission=submission,
#             body=self.body
#         )
#         return submission
#
#
# # class DeleteComment(Event):
#     """Deletion of a :class:`.Comment` on a :class:`.domain.submission.Submission`."""
#
#     read_scope = 'submission:moderate'
#     write_scope = 'submission:moderate'
#
#     comment_id: str = field(default_factory=str)
#
#     def validate_pre_lock(self, submission: Submission) -> None:
#         """The :attr:`.comment_id` must present on the submission."""
#         if self.comment_id is None:
#             raise InvalidEvent(self, 'comment_id is required')
#         if not hasattr(submission, 'comments') or not submission.comments:
#             raise InvalidEvent(self, 'Cannot delete nonexistant comment')
#         if self.comment_id not in submission.comments:
#             raise InvalidEvent(self, 'Cannot delete nonexistant comment')
#
#     def project(self, submission: Submission) -> Submission:
#         """Remove the comment from the submission."""
#         del submission.comments[self.comment_id]
#         return submission
#
#
# # class AddDelegate(Event):
#     """Owner delegates authority to another agent."""
#
#     delegate: Optional[Agent] = None
#
#     def validate_pre_lock(self, submission: Submission) -> None:
#         """The event creator must be the owner of the submission."""
#         if not self.creator == submission.owner:
#             raise InvalidEvent(self, 'Event creator must be submission owner')
#
#     def project(self, submission: Submission) -> Submission:
#         """Add the delegate to the submission."""
#         delegation = Delegation(
#             creator=self.creator,
#             delegate=self.delegate,
#             created=self.created
#         )
#         submission.delegations[delegation.delegation_id] = delegation
#         return submission
#
#
# # class RemoveDelegate(Event):
#     """Owner revokes authority from another agent."""
#
#     delegation_id: str = field(default_factory=str)
#
#     def validate_pre_lock(self, submission: Submission) -> None:
#         """The event creator must be the owner of the submission."""
#         if not self.creator == submission.owner:
#             raise InvalidEvent(self, 'Event creator must be submission owner')
#
#     def project(self, submission: Submission) -> Submission:
#         """Remove the delegate from the submission."""
#         if self.delegation_id in submission.delegations:
#             del submission.delegations[self.delegation_id]
#         return submission


class AddFeature(Event):
    """Add feature metadata to a submission."""

    NAME = "add feature metadata"
    NAMED = "feature metadata added"

    feature_type: Feature.Type = \
        field(default=Feature.Type.WORD_COUNT)
    feature_value: Union[float, int] = field(default=0)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Verify that the feature type is a known value."""
        if self.feature_type not in Feature.Type:
            valid_types = ", ".join([ft.value for ft in Feature.Type])
            raise InvalidEvent(self, "Must be one of %s" % valid_types)

    def project(self, submission: Submission) -> Submission:
        """Add the annotation to the submission."""
        assert self.created is not None
        submission.annotations[self.event_id] = Feature(
            event_id=self.event_id,
            creator=self.creator,
            created=self.created,
            proxy=self.proxy,
            feature_type=self.feature_type,
            feature_value=self.feature_value
        )
        return submission


class AddClassifierResults(Event):
    """Add the results of a classifier to a submission."""

    NAME = "add classifer results"
    NAMED = "classifier results added"

    classifier: ClassifierResults.Classifiers \
        = field(default=ClassifierResults.Classifiers.CLASSIC)
    results: List[ClassifierResult] = field(default_factory=list)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Verify that the classifier is a known value."""
        if self.classifier not in ClassifierResults.Classifiers:
            valid = ", ".join([c.value for c in ClassifierResults.Classifiers])
            raise InvalidEvent(self, "Must be one of %s" % valid)

    def project(self, submission: Submission) -> Submission:
        """Add the annotation to the submission."""
        assert self.created is not None
        submission.annotations[self.event_id] = ClassifierResults(
            event_id=self.event_id,
            creator=self.creator,
            created=self.created,
            proxy=self.proxy,
            classifier=self.classifier,
            results=self.results
        )
        return submission


class Reclassify(Event):
    """Change the primary classification of a submission."""

    NAME = "reclassify submission"
    NAMED = "submission reclassified"

    #category: Optional[taxonomy.Category] = None
    category: Optional[str] = None

    def validate_pre_lock(self, submission: Submission) -> None:
        """Validate the primary classification category."""
        assert isinstance(self.category, str)
        validators.must_be_an_active_category(self, self.category, submission)
        self._must_be_unannounced(submission)
        validators.cannot_be_secondary(self, self.category, submission)

    def _must_be_unannounced(self, submission: Submission) -> None:
        """Can only be set on the first version before publication."""
        if submission.arxiv_id is not None or submission.version > 1:
            raise InvalidEvent(self, "Can only be set on the first version,"
                                     " before publication.")

    def project(self, submission: Submission) -> Submission:
        """Set :attr:`.domain.Submission.primary_classification`."""
        clsn = Classification(category=self.category)
        submission.primary_classification = clsn
        return submission
