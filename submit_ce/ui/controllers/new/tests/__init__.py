from datetime import datetime, timezone, timedelta
from unittest import TestCase
from zoneinfo import ZoneInfo

import pytest
from arxiv.auth.auth import scopes
from arxiv.auth import domain
from arxiv.taxonomy.definitions import CATEGORIES

import submit_ce


class CtrlBase(TestCase):

    @pytest.fixture(autouse=True)
    def add_app(self, app):
        self.app = app

    @pytest.fixture(autouse=True)
    def add_auth_user(self, authorized_user_session):
        session, jwt = authorized_user_session
        self.session = session

    # def setup(self: TestCase):
    #     """Create an authenticated session."""
    #     # Specify the validity period for the session.
    #     start = datetime.now(ZoneInfo('US/Eastern'))
    #     end = start + timedelta(seconds=36000)
    #     self.session = domain.Session(
    #         session_id='123-session-abc',
    #         start_time=start, end_time=end,
    #         user=domain.User(
    #             user_id='235678',
    #             email='foo@foo.com',
    #             username='foouser',
    #             name=domain.UserFullName(forename="Jane", surname="Bloggs", suffix="III"),
    #
    #             profile=domain.UserProfile(
    #                 affiliation="FSU",
    #                 rank=3,
    #                 country="de",
    #                 default_category=CATEGORIES['astro-ph.GA'],
    #                 submission_groups=['grp_physics']
    #             )
    #         ),
    #         authorizations=domain.Authorizations(
    #             scopes=[scopes.CREATE_SUBMISSION,
    #                     scopes.EDIT_SUBMISSION,
    #                     scopes.VIEW_SUBMISSION],
    #             endorsements=[CATEGORIES['astro-ph.CO'],
    #                           CATEGORIES['astro-ph.GA']]
    #         )
    #     )
