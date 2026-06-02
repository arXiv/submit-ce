"""Tests for :mod:`submit_ce.ui.controllers.new.review`."""

from http import HTTPStatus as status
from unittest.mock import MagicMock

from werkzeug.datastructures import MultiDict

from submit_ce.ui.controllers.new import review


def test_review_files_get_warning_via_http(app, authorized_client, sub_files,
                                           mocker):
    """End-to-end: GET /<id>/review_files triggers flash_warning when
    _load_or_create_preflight yields no preflight data."""
    mocker.patch.object(review, '_load_or_create_preflight',
                        return_value=(None, None))
    mock_flash = mocker.patch.object(review.alerts, 'flash_warning')

    url = f"/{sub_files.submission_id}/review_files"
    resp = authorized_client.get(url)

    assert resp.status_code == status.OK
    assert mock_flash.called
    # Flash text changed when the page was redesigned to show a clearer
    # placeholder instead of bare empty form controls. Assert on the
    # title and a stable substring of the body.
    assert mock_flash.call_args[1].get('title') == 'Preflight unavailable'
    assert "preflight service is temporarily unavailable" in str(
        mock_flash.call_args[0][0])
