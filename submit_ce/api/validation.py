from typing import Dict, List, Union, Tuple

from fastapi import UploadFile

from submit_ce.api.domain import User, Client, Submission
from submit_ce.api.domain.events import VerifyUser, SetMetadata, SetCategories, AuthorshipDirect, AuthorshipProxy, \
    SetLicense, AgreedToPolicy, StartedNew
from submit_ce.api.domain.meta import CategoryChange
from submit_ce.api.implementations import BaseDefaultApi

"""
The goal of this is to have a way to have consistant validation even with
different API implementations.

Is there a better way to do this?

NG did event sourcing and validated the not yet applied event. CE does not have
an explicit requirement to do event sourcing and so far it does not seem the way
to go.

This was originally a wrapper that had an inner BaseDefaultApi and validated
before the call to that. But then it needed to get the submission before it made
the inner call and that seemed inefficent.
"""
class Validator():
    def __init__(self, submission: Submission, inner: BaseDefaultApi):
        self.inner = inner
        self.submission = submission

    def basic_checks(self, impl_data: Dict, user: User, client: Client) -> List[str]:
        if self.is_announced():
            return ["Cannot alter an announced submission."]
        if self.is_locked():
            return ["Submission is currently locked."]

    def get_submission(self, impl_data: Dict, user: User, client: Client, submission_id: str) -> List[str]:
        # this might not make sense to validate
        return []

    def start(self, impl_data: Dict, user: User, client: Client, started: Union[StartedNew]) -> str:
        return []

    def accept_policy_post(self, impl_data: Dict, user: User, client: Client, submission_id: str,
                           agreement: AgreedToPolicy) -> object:
        probs = self.basic_checks(impl_data, user, client)
        if agreement and agreement.accepted_policy_id:
            probs.append("You must agree to the policy before continuing.")

        return probs

    def mark_deposited_post(self, impl_data: Dict, user: User, client: Client, submission_id: str) -> None:
        return []

    def mark_processing_for_deposit_post(self, impl_data: Dict, user: User, client: Client, submission_id: str) -> None:
        return []

    def unmark_processing_for_deposit_post(self, impl_data: Dict, user: User, client: Client, submission_id: str) -> None:
        return []

    def set_license_post(self, impl_data: Dict, user: User, client: Client, submission_id: str, license: SetLicense) -> None:
        probs = self.basic_checks(impl_data, user, client)
        if not license or not license.license_uri:
            probs.append("Must indicate a license.")

        return probs

    def assert_authorship_post(self, impl_data: Dict, user: User, client: Client, submission_id: str, authorship: Union[AuthorshipDirect, AuthorshipProxy]) -> str:
        probs = self.basic_checks(impl_data, user, client)
        if not authorship or \
            isinstance(authorship, AuthorshipDirect) and not authorship.i_am_author:
            probs.append("Must indicate authorship.")
        if isinstance(authorship,AuthorshipProxy):
            if not authorship.i_am_authorized_to_proxy:
                probs.append("You must be authorized to proxy to set a proxy authorship.")
            if not authorship.proxy:
                probs.append("You must indicate who you are a proxy for.")

        return probs



    def file_post(self, impl_data: Dict, user: User, client: Client, submission_id: str, uploadFile: UploadFile):
        return self.basic_checks(impl_data, user, client)

    def set_categories_post(self, impl_data: Dict, user: User, client: Client, submission_id: str,
                            set_categoires: SetCategories) -> CategoryChange:
        # From NG events:
        # if set primary:
        # validators.must_be_an_active_category(self, self.category, submission)
        # self._creator_must_be_endorsed(submission)
        # self._must_be_unannounced(submission)
        # validators.submission_is_not_finalized(self, submission)
        # validators.cannot_be_secondary(self, self.category, submission)

        # if add secondary:
        # validators.must_be_an_active_category(self, self.category, submission)
        # validators.cannot_be_primary(self, self.category, submission)
        # validators.cannot_be_secondary(self, self.category, submission)
        # validators.max_secondaries(self, submission)
        # validators.no_redundant_general_category(self, self.category, submission)
        # validators.no_redundant_non_general_category(self, self.category, submission)
        # validators.cannot_be_genph(self, self.category, submission)

        #if remove secondary:
        # assert self.category is not None
        # validators.must_be_an_active_category(self, self.category, submission)
        # self._must_already_be_present(submission)
        # validators.submission_is_not_finalized(self, submission)

        probs = self.basic_checks(impl_data, user, client)


    def set_metadata_post(self, impl_data: Dict, user: User, client: Client, submission_id: str,
                          metadata: Union[SetMetadata]):
        probs = self.basic_checks(impl_data, user, client)

    def user_submissions(self, impl_data: Dict, user: User, client: Client) -> List[Submission]:
        return []

    def verify_user_post(self, impl_data: Dict, user: User, client: Client, submission_id: str, verifyUser: VerifyUser):
        probs = self.basic_checks(impl_data, user, client)

    def get_service_status(self, impl_data: Dict) -> Tuple[bool, str]:
        return []

    def is_locked(self):
        # TODO implement
        return False

    def is_announced(self):
        return self.submission.is_announced

    def is_submitted(self):
        return self.submission.is_submitted
