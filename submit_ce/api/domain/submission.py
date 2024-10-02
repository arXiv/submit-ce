"""Data structures for submissions."""

import hashlib
from dataclasses import field
from enum import Enum
from typing import Optional, Dict, List, Iterable, Set, Any, Literal

from dateutil.parser import parse as parse_date
from pydantic import BaseModel, AwareDatetime
from pydantic.dataclasses import dataclass

from .agent import Agent
from .annotation import Comment, Feature, Annotation
from .flag import Flag, flag_factory
from .meta import License, Classification
from .preview import Preview
from .process import ProcessStatus
from .proposal import Proposal
from .util import get_tzaware_utc_now, dict_coerce, list_coerce


@dataclass
class Author:
    """Represents an author of a submission."""

    order: int = field(default=0)
    forename: str = field(default_factory=str)
    surname: str = field(default_factory=str)
    initials: str = field(default_factory=str)
    affiliation: str = field(default_factory=str)
    email: str = field(default_factory=str)
    identifier: Optional[str] = field(default=None)
    display: Optional[str] = field(default=None)
    """
    Submitter may include a preferred display name for each author.

    If not provided, will be automatically generated from the other fields.
    """

    def _generate_identifier(self) -> str:
        h = hashlib.new('sha1')
        h.update(bytes(':'.join([self.forename, self.surname, self.initials,
                                 self.affiliation, self.email]),
                       encoding='utf-8'))
        return h.hexdigest()

    @property
    def canonical(self) -> str:
        """Canonical representation of the author name."""
        name = "%s %s %s" % (self.forename, self.initials, self.surname)
        name = name.replace('  ', ' ')
        if self.affiliation:
            return "%s (%s)" % (name, self.affiliation)
        return name


@dataclass
class SubmissionContent:
    """Metadata about the submission source package."""

    class Format(Enum):
        """Supported source formats."""

        UNKNOWN = None
        """We could not determine the source format."""
        INVALID = "invalid"
        """We are able to infer the source format, and it is not supported."""
        TEX = "tex"
        """A flavor of TeX."""
        PDFTEX = "pdftex"
        """A PDF derived from TeX."""
        POSTSCRIPT = "ps"
        """A postscript source."""
        HTML = "html"
        """An HTML source."""
        PDF = "pdf"
        """A PDF-only source."""

    identifier: str
    checksum: str
    uncompressed_size: int # todo change to uncompressed_bytes
    compressed_size: int # todo change to compressed_bytes
    source_format: Format = Format.UNKNOWN


@dataclass
class SubmissionMetadata:
    """Metadata about a :class:`.domain.submission.Submission` instance."""

    title: Optional[str] = None
    abstract: Optional[str] = None

    authors: List[Author] = field(default_factory=list)
    authors_display: str = field(default_factory=str)
    """The canonical arXiv author string."""

    doi: Optional[str] = None
    msc_class: Optional[str] = None
    acm_class: Optional[str] = None
    report_num: Optional[str] = None
    journal_ref: Optional[str] = None

    comments: Optional[str] = field(default_factory=str)


@dataclass
class Hold:
    """Represents a block on announcement, usually for QA/QC purposes."""

    class HoldType(Enum):
        """Supported holds in the submission system."""

        PATCH = 'patch'
        """A hold generated from the classic submission system."""

        SOURCE_OVERSIZE = "source_oversize"
        """The submission source is oversize."""

        PDF_OVERSIZE = "pdf_oversize"
        """The submission PDF is oversize."""

    event_id: str
    """The event that created the hold."""

    creator: Agent
    created: AwareDatetime = field(default_factory=get_tzaware_utc_now)
    hold_type: str = field(default=HoldType.PATCH)
    hold_reason: Optional[str] = field(default_factory=str)



@dataclass
class Waiver:
    """Represents an exception or override."""

    event_id: str
    """The identifier of the event that produced this waiver."""
    waiver_type: Hold.HoldType
    waiver_reason: str
    created: AwareDatetime
    creator: Agent


# UserRequest seems to be a barely implemented feature.
# reassess if it makes sense or of something else should be done.

# class UserRequest(BaseModel):
#     """Represents a user request related to a submission."""
#
#     NAME:str = "User request base"
#
#     class Status(Enum):
#         WORKING = 'working'
#         """Request is not yet submitted."""
#         PENDING = 'pending'
#         """Request is pending approval."""
#         REJECTED = 'rejected'
#         """Request has been rejected."""
#         APPROVED = 'approved'
#         """Request has been approved."""
#         APPLIED = 'applied'
#         """Submission has been updated on the basis of the approved request."""
#         CANCELLED = 'cancelled'
#
#     request_id: str
#     creator: Agent
#     created: AwareDatetime = field(default_factory=get_tzaware_utc_now)
#     updated: AwareDatetime = field(default_factory=get_tzaware_utc_now)
#     status: Literal['working','pending','rejected','approved','applied','cancelled'] = field(default='pending')
#     request_type: str = field(default_factory=str)
#
#     def get_request_type(self) -> str:
#         """Name (str) of the type of user request."""
#         return type(self).__name__
#
#     def is_pending(self) -> bool:
#         """Check whether the request is pending."""
#         return self.status == 'pending'
#
#     def is_approved(self) -> bool:
#         """Check whether the request has been approved."""
#         return self.status == 'approved'
#
#     def is_applied(self) -> bool:
#         """Check whether the request has been applied."""
#         return self.status == 'applied'
#
#     def is_rejected(self) -> bool:
#         """Check whether the request has been rejected."""
#         return self.status == 'rejected'
#
#     def is_active(self) -> bool:
#         """Check whether the request is active."""
#         return self.is_pending() or self.is_approved()
#
#     @classmethod
#     def generate_request_id(cls, submission: 'Submission', N: int = -1) -> str:
#         """Generate a unique identifier for this request."""
#         h = hashlib.new('sha1')
#         if N < 0:
#             N = len([rq for rq in submission.iter_requests if type(rq) is cls])
#         h.update(f'{submission.submission_id}:{cls.NAME}:{N}'.encode('utf-8'))
#         return h.hexdigest()
#
#     def apply(self, submission: 'Submission') -> 'Submission':
#         """Stub for applying the proposal."""
#         raise NotImplementedError('Must be implemented by child class')
#


submission_status = Literal[
    'working',
    'submitted',
    'scheduled',
    'announced',
    'deleted',
    'error',
    'withdrawn',
]

class Submission(BaseModel):
    """
    Represents an arXiv submission object.

    Below this are some ideas from NG that we are not wed to.
    
    Some notable differences between this view of submissions and the classic
    model:

    - There is no "hold" status. Status reflects where the submission is
      in the pipeline. Holds are annotations that can be applied to the
      submission, and may impact its ability to proceed (e.g. from submitted
      to scheduled). Submissions that are in working status can have holds on
      them!
    - We use `arxiv_id` instead of `paper_id` to refer to the canonical arXiv
      identifier for the e-print (once it is announced).
    - Instead of having a separate "submission" record for every change to an
      e-print (e.g. replacement, jref, etc), we represent the entire history
      as a single submission. Announced versions can be found in
      :attr:`.versions`. Withdrawal and cross-list requests can be found in
      :attr:`.user_requests`. JREFs are treated like they "just happen",
      reflecting the forthcoming move away from storing journal ref information
      in the core metadata record.

    """

    creator: Agent
    owner: Agent
    proxy: Optional[Agent] = None
    client: Optional[Agent] = field(default=None)
    created: Optional[AwareDatetime] = field(default=None)
    updated: Optional[AwareDatetime] = field(default=None)
    submitted: Optional[AwareDatetime] = field(default=None)
    submission_id: Optional[int] = field(default=None)

    source_content: Optional[SubmissionContent] = field(default=None)
    preview: Optional[Preview] = field(default=None)

    metadata: SubmissionMetadata = field(default_factory=SubmissionMetadata)
    primary_classification: Optional[Classification] = field(default=None)
    secondary_classification: List[Classification] = \
        field(default_factory=list)
    submitter_contact_verified: bool = field(default=False)
    submitter_is_author: Optional[bool] = field(default=None)
    submitter_accepts_policy: Optional[bool] = field(default=None)
    is_source_processed: bool = field(default=False)
    submitter_confirmed_preview: bool = field(default=False)
    license: Optional[License] = field(default=None)
    status: submission_status = field(default='working')
    """Disposition within the submission pipeline."""

    arxiv_id: Optional[str] = field(default=None)
    """The announced arXiv paper ID."""

    version: int = field(default=1)

    reason_for_withdrawal: Optional[str] = field(default=None)
    """If an e-print is withdrawn, the submitter is asked to explain why."""

    versions: List['Submission'] = field(default_factory=list)
    """Announced versions of this :class:`.domain.submission.Submission`."""

    # These fields are related to moderation/quality control.
    # user_requests: Dict[str, UserRequest] = field(default_factory=dict)
    # """Requests from the owner for changes that require approval."""

    proposals: Dict[str, Proposal] = field(default_factory=dict)
    """Proposed changes to the submission, e.g. reclassification."""

    processes: List[ProcessStatus] = field(default_factory=list)
    """Information about automated processes."""

    annotations: Dict[str, Annotation] = field(default_factory=dict)
    """Quality control annotations."""

    flags: Dict[str, Flag] = field(default_factory=dict)
    """Quality control flags."""

    comments: Dict[str, Comment] = field(default_factory=dict)
    """Moderation/administrative comments."""

    holds: Dict[str, Hold] = field(default_factory=dict)
    """Quality control holds."""

    waivers: Dict[str, Waiver] = field(default_factory=dict)
    """Quality control waivers."""

    @property
    def features(self) -> Dict[str, Feature]:
        return {k: v for k, v in self.annotations.items()
                if isinstance(v, Feature)}

    @property
    def is_active(self) -> bool:
        """Actively moving through the submission workflow."""
        return self.status not in ['deleted','announced']

    @property
    def is_announced(self) -> bool:
        """The submission has been announced."""
        if self.status == 'announced':
            assert self.arxiv_id is not None
            return True
        return False

    @property
    def is_finalized(self) -> bool:
        """Submitter has indicated submission is ready for publication."""
        return self.status not in ['working', 'deleted']

    @property
    def is_deleted(self) -> bool:
        """Submission is removed."""
        return self.status == 'deleted'

    @property
    def primary_category(self) -> str:
        """The primary classification category (as a string)."""
        assert self.primary_classification is not None
        return str(self.primary_classification.category)

    @property
    def secondary_categories(self) -> List[str]:
        """Category names from secondary classifications."""
        return [c.category for c in self.secondary_classification]

    @property
    def is_on_hold(self) -> bool:
        # We need to explicitly check ``status`` here because classic doesn't
        # have a representation for Hold events.
        return (self.status == 'submitted'
                and len(self.hold_types - self.waiver_types) > 0)

    def has_waiver_for(self, hold_type: Hold.HoldType) -> bool:
        return hold_type in self.waiver_types

    @property
    def hold_types(self) -> Set[Hold.HoldType]:
        return set([hold.hold_type for hold in self.holds.values()])

    @property
    def waiver_types(self) -> Set[Hold.HoldType]:
        return set([waiver.waiver_type for waiver in self.waivers.values()])
    #
    # @property
    # def has_active_requests(self) -> bool:
    #     return len(self.active_user_requests) > 0
    #
    # @property
    # def iter_requests(self) -> Iterable[UserRequest]:
    #     return self.user_requests.values()
    #
    # @property
    # def active_user_requests(self) -> List[UserRequest]:
    #     return sorted(filter(lambda r: r.is_active(), self.iter_requests),
    #                   key=lambda r: r.created)
    #
    # @property
    # def pending_user_requests(self) -> List[UserRequest]:
    #     return sorted(filter(lambda r: r.is_pending(), self.iter_requests),
    #                   key=lambda r: r.created)
    #
    # @property
    # def rejected_user_requests(self) -> List[UserRequest]:
    #     return sorted(filter(lambda r: r.is_rejected(), self.iter_requests),
    #                   key=lambda r: r.created)
    #
    # @property
    # def approved_user_requests(self) -> List[UserRequest]:
    #     return sorted(filter(lambda r: r.is_approved(), self.iter_requests),
    #                   key=lambda r: r.created)
    #
    # @property
    # def applied_user_requests(self) -> List[UserRequest]:
    #     return sorted(filter(lambda r: r.is_applied(), self.iter_requests),
    #                   key=lambda r: r.created)

    def __post_init__(self) -> None:
        # if isinstance(self.creator, dict):
        #     self.creator = agent_factory(**self.creator)
        # if isinstance(self.owner, dict):
        #     self.owner = agent_factory(**self.owner)
        # if self.proxy and isinstance(self.proxy, dict):
        #     self.proxy = agent_factory(**self.proxy)
        # if self.client and isinstance(self.client, dict):
        #     self.client = agent_factory(**self.client)
        if isinstance(self.created, str):
            self.created = parse_date(self.created)
        if isinstance(self.updated, str):
            self.updated = parse_date(self.updated)
        if isinstance(self.submitted, str):
            self.submitted = parse_date(self.submitted)
        if isinstance(self.source_content, dict):
            self.source_content = SubmissionContent(**self.source_content)
        if isinstance(self.preview, dict):
            self.preview = Preview(**self.preview)
        if isinstance(self.primary_classification, dict):
            self.primary_classification = \
                Classification(**self.primary_classification)
        if isinstance(self.metadata, dict):
            self.metadata = SubmissionMetadata(**self.metadata)
        # self.delegations = dict_coerce(Delegation, self.delegations)
        self.secondary_classification = \
            list_coerce(Classification, self.secondary_classification)
        if isinstance(self.license, dict):
            self.license = License(**self.license)
        self.versions = list_coerce(Submission, self.versions)
        # self.user_requests = dict_coerce(request_factory, self.user_requests)
        self.proposals = dict_coerce(Proposal, self.proposals)
        self.processes = list_coerce(ProcessStatus, self.processes)
        #self.annotations = dict_coerce(annotation_factory, self.annotations)
        self.flags = dict_coerce(flag_factory, self.flags)
        self.comments = dict_coerce(Comment, self.comments)
        self.holds = dict_coerce(Hold, self.holds)
        self.waivers = dict_coerce(Waiver, self.waivers)
