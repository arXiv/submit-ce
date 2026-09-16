"""What a depositor receives when something fails that is not a `SwordFault`.

Every other test in this suite drives a *planned* refusal, where the code raises
`SwordFault` and the handler at ``app.py`` renders it. This file covers the other
half: a bug, a database error, a domain event the ingest ladder did not anticipate.

It matters because SWORD clients parse the response as XML unconditionally. An
HTML 500 page is not "an error the client reports" -- it is a parse failure, which
looks to the depositor like a broken server rather than a rejected deposit.

``TestClient`` needs ``raise_server_exceptions=False`` here. Starlette's
``ServerErrorMiddleware`` sends the handler's response *and then re-raises*, so the
exception surfaces in the server log; the default test client turns that re-raise
into a test error and never lets the body be inspected. Production clients get the
response.
"""

import logging

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from submit_ce.sword.atom import ns
from submit_ce.sword.tests.client import basic_auth

ENAVL_CODE = "64"
"""``Config.pm:82`` -- service temporarily unavailable."""

BOOM = "credentials for the internal service are bogus"
"""Stands in for the sort of message a real failure carries: not for depositors."""


@pytest.fixture
def failing_client(sword_app):
    """A client whose deposits blow up inside the route."""
    def explode(*args, **kwargs):
        raise RuntimeError(BOOM)

    sword_app.state.deposits.allocate_id = explode
    return TestClient(sword_app, base_url="https://arxiv.org",
                      raise_server_exceptions=False)


def _deposit(client, depositor):
    return client.post(
        "/sword-app/cs-collection", content=b"PK\x03\x04 a zip",
        headers={"Authorization": basic_auth(depositor.nickname,
                                             depositor.password),
                 "Content-Type": "application/zip"})


# ------------------------------------------------------------- the error document


def test_an_unexpected_error_is_still_a_sword_error(failing_client, depositor):
    response = _deposit(failing_client, depositor)
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/xml")

    root = etree.fromstring(response.content)
    assert root.tag == ns.qname(ns.SWORD, "error")
    assert root.findtext(ns.qname(ns.ARXIV, "errorcode")) == ENAVL_CODE


def test_the_summary_says_only_that_the_service_is_unavailable(failing_client,
                                                               depositor):
    root = etree.fromstring(_deposit(failing_client, depositor).content)
    assert root.findtext(ns.qname(ns.ATOM, "summary")) == \
        "service temporarily unavailable: unexpected error handling the request"


def test_no_internal_detail_reaches_the_depositor(failing_client, depositor):
    """A third party must not be told what broke, or where.

    The message, the exception class and the module path are all absent -- the
    traceback goes to the log instead (see below).
    """
    body = _deposit(failing_client, depositor).text
    assert BOOM not in body
    assert "RuntimeError" not in body
    assert "Traceback" not in body
    assert "submit_ce" not in body


def test_the_traceback_is_logged(failing_client, depositor, caplog):
    """Losing the detail from the response only works if the log keeps it."""
    with caplog.at_level(logging.ERROR, logger="submit_ce.sword.app"):
        _deposit(failing_client, depositor)

    record = next(r for r in caplog.records if "unhandled error" in r.message)
    assert record.exc_info is not None, "logged without the traceback"
    assert "POST" in record.getMessage()
    assert "/sword-app/cs-collection" in record.getMessage()
    assert BOOM in caplog.text


# ------------------------------------------------------- planned faults still win


def test_a_planned_fault_is_not_swallowed_by_the_catch_all(failing_client):
    """`SwordFault` has its own handler and must keep reaching it.

    Registering a handler for `Exception` is easy to get wrong in the direction of
    catching everything: authentication would start answering 503 instead of 401,
    and clients would retry forever rather than fixing their credentials.
    """
    response = failing_client.get("/sword-app/servicedocument")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="SWORD at arXiv"'
    root = etree.fromstring(response.content)
    assert root.findtext(ns.qname(ns.ARXIV, "errorcode")) == "33554432"


def test_a_healthy_deposit_is_unaffected(client, depositor):
    """The handler must not change the happy path."""
    assert _deposit(client, depositor).status_code == 201
