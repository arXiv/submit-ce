"""Core persistence methods for submissions and submission events."""
import contextlib
from typing import List, Tuple, Optional, Dict, Union

from arxiv.auth.auth.tokens import decode
from fastapi import UploadFile
from flask import request
from pydantic import SecretStr
from werkzeug.exceptions import Unauthorized

from submit_ce.api.domain import User, Client
from submit_ce.api.domain.events import SetLicense, AgreedToPolicy, StartedNew, SetMetadata, SetCategories, \
    AuthorshipDirect, AuthorshipProxy
from submit_ce.api.domain.meta import CategoryChange

from arxiv.db import Session, session_factory, _classic_engine, configure_db

from submit_ce.api.implementations import BaseDefaultApi
from submit_ce.api.implementations.legacy_implementation import models
from submit_ce.ui.config import settings
from submit_ce.ui.domain import Submission
from submit_ce.ui.domain.event import Event, CreateSubmission
from submit_ce.ui.exceptions import NoSuchSubmission, NothingToDo

import logging

logger = logging.getLogger(__name__)

def config_backend_api(settings)-> None:
    engine, _ = configure_db(settings)
    session_factory.configure(
        bind=engine,
    #     binds={
    #     models.Base: engine,
    # },
    )


api: BaseDefaultApi = settings.submission_api_implementation.impl
"""BACKEND WITH LEGACY IMPL ONLY FOR TESTING."""


def get_user() -> User:
    # def get_user_impl(request: Request, token: str) -> Optional[User]:
    #  secret = settings.jwt_secret
    #  if isinstance(secret, SecretStr):
    #      secret = secret.get_secret_value()

    #session = decode(token, secret)
    session = request.environ['auth']
    if session is None:
        raise Unauthorized()

    return User(
        identifier=session.user.user_id,
        forename=session.user.name.forename,
        surname=session.user.name.surname,
        suffix=session.user.name.suffix,
        email=session.user.email,
        affiliation=session.user.profile.affiliation,
        endorsements=[],  # TODO where are endorsements other than the db? are they submission groups in the jwt?
        agent_type="User",
    )


def get_client() -> Client:
    ua = request.headers.get("User-Agent", None)
    if ua is None:
        agent_type = "ua-not-set"
    if ua.lower().startswith("mozilla"):
        agent_type = "browser"
    else:
        agent_type = ua[:20]

    # todo hostname
    return Client(
        remoteAddress=request.remote_addr,
        remoteHost="",
        agent_type=agent_type,
        # agent_version="v223432"
    )

def impl_data() -> dict:
    return {"session": Session}

def load(submission_id: int) -> Tuple[Submission, List[Event]]:
    """
    Load a submission and its history.

    This loads all events for the submission, and generates the most
    up-to-date representation based on those events.

    Parameters
    ----------
    submission_id : str
        Submission identifier.

    Returns
    -------
    :class:`.domain.submission.Submission`
        The current state of the submission.
    list
        Items are :class:`.Event` instances, in order of their occurrence.

    Raises
    ------
    :class:`arxiv.submission.exceptions.NoSuchSubmission`
        Raised when a submission with the passed ID cannot be found.

    """
    api.get_submission({"session": Session}, _get_user(), _get_client(), submission_id)


def load_submissions_for_user(user_id: int) -> List[Submission]:
    """
    Load active :class:`.domain.submission.Submission` for a specific user.

    Parameters
    ----------
    user_id : int
        Unique identifier for the user.

    Returns
    -------
    list
        Items are :class:`.domain.submission.Submission` instances.

    """
    return api.user_submissions({"session": Session}, _get_user(), user_id)

def save(*events: Event, submission_id: Optional[int] = None) \
        -> Tuple[Submission, List[Event]]:
    """
    Commit a set of new :class:`.Event` instances for a submission.

    This will persist the events to the database, along with the final
    state of the submission, and generate external notification(s) on the
    appropriate channels.

    Parameters
    ----------
    events : :class:`.Event`
        Events to apply and persist.
    submission_id : int
        The unique ID for the submission, if available. If not provided, it is
        expected that ``events`` includes a :class:`.CreateSubmission`.

    Returns
    -------
    :class:`arxiv.submission.domain.submission.Submission`
        The state of the submission after all events (including rule-derived
        events) have been applied. Updated with the submission ID, if a
        :class:`.CreateSubmission` was included.
    list
        A list of :class:`.Event` instances applied to the submission. Note
        that this list may contain more events than were passed, if event
        rules were triggered.

    Raises
    ------
    :class:`arxiv.submission.exceptions.NoSuchSubmission`
        Raised if ``submission_id`` is not provided and the first event is not
        a :class:`.CreateSubmission`, or ``submission_id`` is provided but
        no such submission exists.
    :class:`.InvalidEvent`
        If an invalid event is encountered, the entire operation is aborted
        and this exception is raised.
    :class:`.SaveError`
        There was a problem persisting the events and/or submission state
        to the database.

    """
    if len(events) == 0:
        raise NothingToDo('Must pass at least one event')
    events_list = list(events)  # Coerce to list so that we can index.
    prior: List[Event] = []
    before: Optional[Submission] = None

    # We need ACIDity surrounding the the validation and persistence of new
    # events.
    # with classic.transaction():
    #     # Get the current state of the submission from past events. Normally we
    #     # would not want to load all past events, but legacy components may be
    #     # active, and the legacy projected state does not capture all of the
    #     # detail in the event model.
    #     if submission_id is not None:
    #         # This will create a shared lock on the submission rows while we
    #         # are working with them.
    #         before, prior = classic.get_submission(submission_id,
    #                                                for_update=True)
    #
    #     # Either we need a submission ID, or the first event must be a
    #     # creation.
    #     elif events_list[0].submission_id is None \
    #             and not isinstance(events_list[0], CreateSubmission):
    #         raise NoSuchSubmission('Unable to determine submission')
    #
    #     committed: List[Event] = []
    #     for event in events_list:
    #         # Fill in submission IDs, if they are missing.
    #         if event.submission_id is None and submission_id is not None:
    #             event.submission_id = submission_id
    #
    #         # The created timestamp should be roughly when the event was
    #         # committed. Since the event projection may refer to its own ID
    #         # (which is based) on the creation time, this must be set before
    #         # the event is applied.
    #         event.created = datetime.now(UTC)
    #         # Mutation happens here; raises InvalidEvent.
    #         logger.debug('Apply event %s: %s', event.event_id, event.NAME)
    #         after = event.apply(before)
    #         committed.append(event)
    #         if not event.committed:
    #             after, consequent_events = event.commit(_store_event)
    #             committed += consequent_events
    #
    #         before = after      # Prepare for the next event.
    #
    #     all_ = sorted(set(prior) | set(committed), key=lambda e: e.created)
    #     return after, list(all_)
    raise NotImplementedError()
