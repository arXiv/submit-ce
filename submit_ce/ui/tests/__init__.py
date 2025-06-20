"""Tests for the application as a whole."""
from unittest import TestCase

import pytest


class CtrlBase(TestCase):

    @pytest.fixture(autouse=True)
    def add_app(self, app):
        self.app = app

    @pytest.fixture(autouse=True)
    def add_auth_user(self, authorized_user_session):
        session, jwt = authorized_user_session
        self.session = session

    @pytest.fixture(autouse=True)
    def add_auth_client(self, authorized_client):
        self.client = authorized_client
