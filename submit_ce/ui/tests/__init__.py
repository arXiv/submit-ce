"""Tests for the application as a whole."""

from unittest import TestCase

import pytest

from flask import testing
from werkzeug.datastructures import Headers

from submit_ce.domain.submission import Submission


class ClientArxivAuth(testing.FlaskClient):
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
        super(ClientArxivAuth, self).__init__( *args, **kwargs)

    def open(self, *args, **kwargs):
        api_key_headers = Headers({
            'Authorization': self._jwt
        })
        headers = kwargs.pop('headers', Headers())
        if isinstance(headers, dict):
            for key,val in api_key_headers.items():
                headers[key]=val
        else:
            headers.extend(api_key_headers)
        kwargs['headers'] = headers
        return super().open(*args, **kwargs)

class CtrlBase(TestCase):

    @pytest.fixture(autouse=True)
    def add_app(self, app):
        self.app = app

    @pytest.fixture(autouse=True)
    def add_auth_user(self, authorized_user_session, authorized_user):
        session, jwt = authorized_user_session
        self.session = session
        self.user = authorized_user


    @pytest.fixture(autouse=True)
    def add_auth_client(self, authorized_client):
        self.client = authorized_client



def gets(appx, subx) -> Submission:
    """Helper to get submission from a context."""
    with appx.app_context():
        return appx.api.get(subx.submission_id)
