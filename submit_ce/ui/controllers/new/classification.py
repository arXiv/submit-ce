"""Controller for classification actions.

** Does form handling in cases outside of wtforms. **

Creates an events of type:
 - `core.events.event.SetPrimaryClassification`
 - `core.events.event.AddSecondaryClassification`
 - `core.events.event.RemoveSecondaryClassification`

The forms on this are a bit tricky since it will stage added or removed
secondaries and only save those and the primary on "save & continue".

General idea is to have the state rendered on the form, and submitted back
to controller. The state has the existing saved categories and staged changes.
The staged are only saved on "save & continue".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus as status
from typing import Optional, Tuple, Dict, Any

from arxiv import taxonomy
from arxiv.auth.domain import Session
from arxiv.forms import csrf
from arxiv.taxonomy.category import Category
from arxiv.taxonomy.definitions import CATEGORIES_ACTIVE, ARCHIVES_ACTIVE

from submit_ce.api import User
from submit_ce.api.domain.meta import Classification
from submit_ce.ui.backend import endorsed_for
from submit_ce.ui.auth import user_and_client_from_session
from werkzeug.datastructures import MultiDict
from wtforms import (
    Field,
    SelectField,
    SelectMultipleField,
    TextAreaField,
    widgets,
    HiddenField,
    validators,
)
from flask import current_app, request

from submit_ce.api.domain import Submission
from submit_ce.api.domain.event import (
    RemoveSecondaryClassification,
    AddSecondaryClassification,
    SetPrimaryClassification,
)
from submit_ce.ui.controllers.util import OptGroupSelectField, validate_command, validate_commands
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
from submit_ce.ui.backend import get_submission

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103

STAGE_ADD = "STAGE_ADD"
STAGE_REMOVE = "STAGE_REMOVE"
SAVE = "SAVE"

CATEGORIES = [
    (
        archive.id,
        [
            (category_id, f"{category_id}  {category.full_name}")
            for category_id, category in CATEGORIES_ACTIVE.items()
            if category.in_archive == archive_id
        ],
    )
    for archive_id, archive in ARCHIVES_ACTIVE.items()
]
"""Categories grouped by archive."""


def _cat(cat: str | Classification | None) -> Optional[Category]:
    if cat is None or not cat:
        return None
    if isinstance(cat, Classification):
        return taxonomy.definitions.CATEGORIES[cat.category]
    else:
        return taxonomy.definitions.CATEGORIES[cat]


class HiddenCatetorySet(TextAreaField):
    """Hidden field for a `Set` of staged category changes."""

    def _value(self):
        if self.data:
            return ",".join(self.data)
        else:
            return ""

    def process_formdata(self, valuelist):
        if valuelist:
            self.data = set([x.strip() for x in valuelist[0].split(",") if x.strip()])
        else:
            self.data = set()


class ClassificationFormV2(csrf.CSRFForm):
    """Represents the state of the classification page from the request."""

    # user_id = IntegerField(widget=HiddenInput())
    primary = OptGroupSelectField("Primary Category", choices=CATEGORIES, default="")
    """On get primary is loaded from saved, or user default primary.
    On POST operation other than SAVE, it should keep whatever is in the form."""
    add_secondary = OptGroupSelectField(choices=CATEGORIES, default="")

    secondaries_staged_add = HiddenCatetorySet()
    secondaries_staged_remove = HiddenCatetorySet()

    def fitler_primary_choices(self, user: User)->None:
        p_options = []
        for archive, archive_choices in CATEGORIES:
            cat_list = []
            for category, display in archive_choices:
                if endorsed_for(user, category):
                    cat_list.append((category, display))
            if cat_list:
                p_options.append((archive, cat_list))
        self.primary.choices = [(archive, _choices) for archive, _choices in p_options if _choices]

    def filter_choices(self, submission: Submission, user: User) -> None:
        """Remove redundant choices, and limit to endorsed categories."""

        primary = (self.primary.data) or (
            submission.primary_classification.category
            if submission.primary_classification
            and submission.primary_classification.category
            else ""
        )

        options = []
        for archive, archive_choices in CATEGORIES:
            cat_list = []
            for category, display in archive_choices:
                if not endorsed_for(user, category) or category == primary:
                    continue

                already_saved = category in submission.secondary_categories
                already_staged = self.secondaries_staged_add.data and \
                    category in self.secondaries_staged_add.data
                staged_for_remove = category in submission.secondary_categories and\
                    self.secondaries_staged_remove.data and \
                    category in self.secondaries_staged_remove.data
                if staged_for_remove or not (already_saved or already_staged):
                    cat_list.append((category, display))

            if cat_list:
                options.append((archive, cat_list))

        self.add_secondary.choices = [(archive, _choices) for archive, _choices in options if _choices]

    def secondaries_save_and_staged(
            self, submission: Submission, user: User
    ) -> list[str]:
        """Gets a list of saved and staged secondaries."""
        self.filter_choices(submission, user)
        saved = set(submission.secondary_categories)
        staged_add = set(self.secondaries_staged_add.data or [])
        staged_remove = set(self.secondaries_staged_remove.data or [])
        return sorted(staged_add | (saved - staged_remove))

    def mutate_stage_secondary_add(self, category:str, submission:Submission):
        in_staged_add = (
                self.secondaries_staged_add.data is not None
                and category in self.secondaries_staged_add.data
            )
        in_staged_remove = (
                self.secondaries_staged_remove.data is not None
                and category in self.secondaries_staged_remove.data
            )

        if in_staged_remove:
            self.secondaries_staged_remove.data.remove(category)

        if not category in submission.secondary_categories:
            self.secondaries_staged_add.data.add(category)

    def mutate_stage_secondary_remove(self, category:str, submission:Submission):
        in_saved_sec = category in submission.secondary_categories
        in_staged_add = (
            self.secondaries_staged_add.data is not None
            and category in self.secondaries_staged_add.data
        )
        in_staged_remove = (
            self.secondaries_staged_remove.data is not None
            and category in self.secondaries_staged_remove.data
        )

        if in_staged_add:
            self.secondaries_staged_add.data.remove(category)
        if in_saved_sec and not in_staged_remove:
            self.secondaries_staged_remove.data.add(category)

    def mutate_primary_change(self, submission:Submission):
        # Does same as mutate_primary_change, alias just make it explicitly stated
        self.mutate_stage_secondary_remove(self.primary.data, submission)

# ############################## CONTROLLER ############################## #
def classification(
    method: str, params: MultiDict, session: Session, submission_id: int, **kwargs
) -> Response:
    """Handle primary classification requests for a new submission."""
    submitter, client = user_and_client_from_session(session)
    submission, _ = get_submission(submission_id)
    primary = _cat(submission.primary_classification)
    primary_cat_id = primary.id if primary else ""

    form = ClassificationFormV2(params)
    form.fitler_primary_choices(submitter)
    response_data = {
        "submission_id": submission_id,
        "submission": submission,
        "submitter": submitter,
        "client": client,
        "form": form,
        "primary": primary,
    }

    if method == "GET":
        form.primary.default = session.user.profile.default_category
        form.primary.data = primary_cat_id
        return response_data, status.OK, {}
    if method != "POST":
        return response_data, status.METHOD_NOT_ALLOWED, {}
    match request.form.get("action","") or request.form.get("operation", "").split(":"):
        case ["STAGE_ADD"]:  # "Add" button on cross-list category drop down
            cat = request.form.get("add_secondary", "")
            form.add_secondary.data = None  # blank field to reused on redisplay
            # todo validate request.form.secondary_category is a category
            if not cat or cat == primary_cat_id:
                return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))
            else:
                form.mutate_stage_secondary_add(cat, submission)
                return stay_on_this_stage((response_data, status.OK, {}))
        case ["STAGE_REMOVE", cat]:   # "Trashcan" button on a secondary
            if not cat:
                return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))
            form.mutate_stage_secondary_remove(cat, submission)
            return stay_on_this_stage((response_data, status.OK, {}))
        case "next":  # green "save&continue" button
            commands = []
            for sec_rm in form.secondaries_staged_remove.data:
                commands.append(RemoveSecondaryClassification(
                    category=sec_rm,
                    creator=submitter,
                    client=client,
                ))

            for sec_add in form.secondaries_staged_add.data:
                commands.append(AddSecondaryClassification(
                    category=sec_add,
                    creator=submitter,
                    client=client,
                ))

            if form.primary.data != primary_cat_id:
                commands.append(SetPrimaryClassification(
                    category=form.primary.data,
                    creator=submitter,
                    client=client
                ))

            if not commands:
                return ready_for_next((response_data, status.OK, {}))

            if not validate_commands(form, commands, submission, "primary"):
                # should not really happen?
                return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))

            submission, _ = current_app.api.save(*commands, submission_id=submission_id)
            response_data["submission"] = submission
            return ready_for_next((response_data, status.OK, {}))
        case _:  # Primary selection change
            form.mutate_primary_change(submission)
            return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))


def cross_list(
    method: str, params: MultiDict, session: Session, submission_id: int, **kwargs
) -> Response:
    """No longer used, merged to single classification page."""
    pass
