"""Tests for the application as a whole."""
from unittest import TestCase

import pytest


from arxiv.auth import auth
from flask import testing, Flask
from werkzeug.datastructures import Headers

from arxiv.taxonomy.definitions import CATEGORIES



class TestClientArxivAuth(testing.FlaskClient):
    """Use to make a Flask client with auth.

    ```python
    with app.app_context():
        generate_token(... some args ...)
        app.test_client_class = TestClientArxivAuth(some_ng_jwt)
        yield app.test_client()
    ```
    """
    def __init__(self, *args, **kwargs):
        self._jwt = kwargs.pop('jwt')
        super(TestClientArxivAuth, self).__init__( *args, **kwargs)

    def open(self, *args, **kwargs):
        api_key_headers = Headers({
            'Authorization': self._jwt
        })
        headers = kwargs.pop('headers', Headers())
        headers.extend(api_key_headers)
        kwargs['headers'] = headers
        return super().open(*args, **kwargs)

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
