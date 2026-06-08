"""Tests for :mod:`submit_ce.ui.controllers.new.review`."""

from http import HTTPStatus as status
from unittest.mock import MagicMock

import pytest
from werkzeug.datastructures import MultiDict

from submit_ce.ui.tests.csrf_util import parse_csrf_token

from submit_ce.domain.compilation import Compilation
from submit_ce.domain.event import SetSourceFormat
from submit_ce.domain.exceptions import InvalidEvent, SaveError
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
    assert "couldn't load preflight data" in mock_flash.call_args[0][0]



def test_review_files_empty_workspace_skips_preflight(
        app, authorized_client, sub_files, mocker):
    """End-to-end: when get_workspace returns None, the controller short-circuits
    via return_to_parent_stage and never calls _load_or_create_preflight."""
    mock_store = MagicMock()
    mock_store.get_workspace.return_value = None
    mocker.patch.object(app.api, 'get_file_store', return_value=mock_store)
    mock_load = mocker.patch.object(review, '_load_or_create_preflight')

    url = f"/{sub_files.submission_id}/review_files"
    resp = authorized_client.get(url)

    assert resp.status_code == status.OK
    mock_load.assert_not_called()


def test_review_files_unsupported_method_raises(mocker):
    """Controller raises MethodNotAllowed for methods other than GET/POST."""
    mocker.patch.object(review, 'user_and_client_from_session',
                        return_value=(MagicMock(), None))
    with pytest.raises(review.MethodNotAllowed):
        review.review_files('PUT', MultiDict(), MagicMock(),
                            'sub1', 'tok')


def _get_csrf(authorized_client, url, mocker):
    """GET the review page (with preflight stubbed out) and pull the CSRF token."""
    mocker.patch.object(review, '_load_or_create_preflight',
                        return_value=(None, None))
    resp = authorized_client.get(url)
    return parse_csrf_token(resp)


def test_review_files_post_with_changes_redirects_to_parent(
        app, authorized_client, sub_files, mocker):
    """End-to-end POST: when _update_preflight reports changes, the controller
    marks STAGE_PARENT and the flow redirects (303 SEE_OTHER)."""
    url = f"/{sub_files.submission_id}/review_files"
    csrf = _get_csrf(authorized_client, url, mocker)

    mock_update = mocker.patch.object(review, '_update_preflight',
                                      return_value=True)
    mock_load_dir = mocker.patch.object(review, '_load_or_create_directives')

    resp = authorized_client.post(url, data={'csrf_token': csrf, 'action': 'next'})

    assert resp.status_code == status.SEE_OTHER
    mock_update.assert_called_once()
    mock_load_dir.assert_not_called()


def test_review_files_post_no_changes_no_preflight_flashes(
        app, authorized_client, sub_files, mocker):
    """End-to-end POST: when there are no changes but preflight is still
    unavailable, the controller flashes a warning and stays on the stage."""
    url = f"/{sub_files.submission_id}/review_files"
    csrf = _get_csrf(authorized_client, url, mocker)

    mocker.patch.object(review, '_update_preflight', return_value=False)
    mocker.patch.object(review, '_load_or_create_directives')
    # Re-patch _load_or_create_preflight: GET used (None, None) for CSRF, POST
    # needs the same so we hit the "preflight unavailable" branch.
    mocker.patch.object(review, '_load_or_create_preflight',
                        return_value=(None, None))
    mock_flash = mocker.patch.object(review.alerts, 'flash_warning')

    resp = authorized_client.post(url, data={'csrf_token': csrf, 'action': 'next'})

    assert resp.status_code == status.OK
    assert mock_flash.called
    assert "Preflight data is not available" in mock_flash.call_args[0][0]


def test_review_files_post_no_changes_stores_zzrm_and_advances(
        app, authorized_client, sub_files, mocker):
    """End-to-end POST: when there are no changes and preflight is present,
    the controller stores the merged zzrm and advances to the next stage."""
    url = f"/{sub_files.submission_id}/review_files"
    csrf = _get_csrf(authorized_client, url, mocker)

    mocker.patch.object(review, '_update_preflight', return_value=False)
    mocker.patch.object(review, '_load_or_create_directives')
    mocker.patch.object(review, '_load_or_create_preflight',
                        return_value=({'tex_files': []}, {'sources': []}))

    # Stub the external preflight/zzrm types to avoid building real fixtures.
    mocker.patch.object(review, 'PreflightResponse')
    fake_zzrm = MagicMock()
    fake_zzrm.to_dict.return_value = {'merged': True}
    mocker.patch.object(review, 'ZeroZeroReadMe', return_value=fake_zzrm)

    mock_store = MagicMock()
    mocker.patch.object(app.api, 'get_file_store', return_value=mock_store)

    resp = authorized_client.post(url, data={'csrf_token': csrf, 'action': 'next'})

    assert resp.status_code == status.SEE_OTHER
    fake_zzrm.from_dict.assert_called_once_with({'sources': []})
    fake_zzrm.update_from_preflight.assert_called_once()
    mock_store.store_zzrm.assert_called_once_with(
        str(sub_files.submission_id), {'merged': True}
    )


def _make_workspace(*paths):
    """Build a stand-in workspace whose `.files` carry the given paths."""
    ws = MagicMock()
    ws.files = [MagicMock(path=p) for p in paths]
    return ws


def test_update_preflight_no_form_no_deletions_returns_false(
        app, authorized_user, mocker):
    """Empty POST (no form fields, no selected files) is a no-op."""
    mocker.patch.object(review, '_get_user_decisions_data', return_value=None)
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        result = review._update_preflight(
            MultiDict(), 'sub1', _make_workspace('paper.tex'),
            authorized_user, None,
        )
    assert result is False
    mock_save.assert_not_called()


def test_update_preflight_selected_files_not_in_workspace_returns_false(
        app, authorized_user, mocker):
    """Paths in selected_files that aren't in the workspace are filtered out;
    with no form fields, the call is a no-op."""
    mocker.patch.object(review, '_get_user_decisions_data', return_value=None)
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        params = MultiDict([('selected_files', 'ghost.tex')])
        result = review._update_preflight(
            params, 'sub1', _make_workspace('paper.tex'),
            authorized_user, None,
        )
    assert result is False
    mock_save.assert_not_called()


def test_update_preflight_files_to_delete_triggers_save(
        app, authorized_user, mocker):
    """A valid file marked for deletion saves SetDecisions and returns True."""
    mocker.patch.object(review, '_get_user_decisions_data', return_value=None)
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        params = MultiDict([('selected_files', 'paper.tex')])
        result = review._update_preflight(
            params, 'sub1', _make_workspace('paper.tex', 'other.tex'),
            authorized_user, None,
        )
    assert result is True
    mock_save.assert_called_once()
    cmd = mock_save.call_args[0][0]
    assert cmd.files_to_delete == ['paper.tex']
    assert mock_save.call_args[1] == {'submission_id': 'sub1'}


def test_update_preflight_decisions_unchanged_returns_false(
        app, authorized_user, mocker):
    """Form fields identical to stored user_decisions: no-op, no save."""
    existing = {
        'sources': [{'filename': 'main.tex'}],
        'texlive_version': '2025',
        'process': {'compiler': 'pdflatex'},
    }
    mocker.patch.object(review, '_get_user_decisions_data',
                        return_value=existing)
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        params = MultiDict([
            ('source_file', 'main.tex'),
            ('compiler', 'pdflatex'),
            ('compiler_version', '2025'),
        ])
        result = review._update_preflight(
            params, 'sub1', _make_workspace('main.tex'),
            authorized_user, None,
        )
    assert result is False
    mock_save.assert_not_called()


def test_update_preflight_decisions_changed_triggers_save(
        app, authorized_user, mocker):
    """Form fields differ from stored user_decisions: SetDecisions saved."""
    existing = {
        'sources': [{'filename': 'main.tex'}],
        'texlive_version': '2024',
        'process': {'compiler': 'pdflatex'},
    }
    mocker.patch.object(review, '_get_user_decisions_data',
                        return_value=existing)
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        params = MultiDict([
            ('source_file', 'main.tex'),
            ('compiler', 'pdflatex'),
            ('compiler_version', '2025'),
        ])
        result = review._update_preflight(
            params, 'sub1', _make_workspace('main.tex'),
            authorized_user, None,
        )
    assert result is True
    mock_save.assert_called_once()
    cmd = mock_save.call_args[0][0]
    assert cmd.decisions['texlive_version'] == '2025'
    assert cmd.files_to_delete == []


def test_update_preflight_no_existing_decisions_triggers_save(
        app, authorized_user, mocker):
    """First-time form submission (no stored decisions) saves SetDecisions."""
    mocker.patch.object(review, '_get_user_decisions_data', return_value=None)
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        params = MultiDict([
            ('source_file', 'main.tex'),
            ('compiler', 'pdflatex'),
            ('compiler_version', '2025'),
        ])
        result = review._update_preflight(
            params, 'sub1', _make_workspace('main.tex'),
            authorized_user, None,
        )
    assert result is True
    mock_save.assert_called_once()


def test_update_preflight_invalid_event_returns_false(
        app, authorized_user, mocker):
    """If api.save raises InvalidEvent, it's swallowed and the call returns False."""
    mocker.patch.object(review, '_get_user_decisions_data', return_value=None)
    with app.app_context():
        mock_save = mocker.patch.object(
            app.api, 'save',
            side_effect=InvalidEvent(MagicMock(), "nope"),
        )
        params = MultiDict([
            ('source_file', 'main.tex'),
            ('compiler', 'pdflatex'),
            ('compiler_version', '2025'),
        ])
        result = review._update_preflight(
            params, 'sub1', _make_workspace('main.tex'),
            authorized_user, None,
        )
    assert result is False
    mock_save.assert_called_once()


def test_populate_form_choices_come_from_enums_and_preflight(app):
    """compiler/compiler_version choices come from Compilation enums;
    source_file choices come from preflight tex_files."""
    preflight = {'tex_files': [{'filename': 'main.tex'}, {'filename': 'sup.tex'}]}
    with app.app_context():
        form = review.ReviewForm(MultiDict(), meta={'csrf': False})
        review._populate_form(form, preflight, None)
        assert form.compiler.choices == [
            (c.value, c.value) for c in Compilation.SupportedCompiler
        ]
        assert form.compiler_version.choices == [
            (v.value, f'TeX Live {v.value}') for v in Compilation.CompilerVersion
        ]
        assert form.source_file.choices == [('main.tex', 'main.tex'),
                                            ('sup.tex', 'sup.tex')]


def test_populate_form_source_file_prefers_user_decisions(app):
    """user_decisions.sources[0].filename wins over preflight detected_toplevel_files."""
    preflight = {
        'tex_files': [{'filename': 'main.tex'}, {'filename': 'chosen.tex'}],
        'detected_toplevel_files': [{'filename': 'main.tex'}],
    }
    user_decisions = {'sources': [{'filename': 'chosen.tex'}]}
    with app.app_context():
        form = review.ReviewForm(MultiDict(), meta={'csrf': False})
        review._populate_form(form, preflight, user_decisions)
        assert form.source_file.data == 'chosen.tex'


def test_populate_form_source_file_falls_back_to_preflight_toplevel(app):
    """With no user_decisions, source_file falls back to preflight detected_toplevel_files."""
    preflight = {
        'tex_files': [{'filename': 'main.tex'}],
        'detected_toplevel_files': [{'filename': 'main.tex'}],
    }
    with app.app_context():
        form = review.ReviewForm(MultiDict(), meta={'csrf': False})
        review._populate_form(form, preflight, None)
        assert form.source_file.data == 'main.tex'


def test_populate_form_compiler_and_version_from_user_decisions(app):
    """user_decisions.process.compiler and process.compiler_version are used when present."""
    preflight = {'tex_files': []}
    user_decisions = {
        'process': {'compiler': 'xelatex', 'compiler_version': '2023'},
    }
    with app.app_context():
        form = review.ReviewForm(MultiDict(), meta={'csrf': False})
        review._populate_form(form, preflight, user_decisions)
        assert form.compiler.data == 'xelatex'
        assert form.compiler_version.data == '2023'


def test_populate_form_compiler_version_falls_back_to_texlive_version(app):
    """If process.compiler_version is missing, the top-level texlive_version is used."""
    preflight = {'tex_files': []}
    user_decisions = {
        'process': {'compiler': 'pdflatex'},
        'texlive_version': '2023',
    }
    with app.app_context():
        form = review.ReviewForm(MultiDict(), meta={'csrf': False})
        review._populate_form(form, preflight, user_decisions)
        assert form.compiler_version.data == '2023'


def test_populate_form_defaults_when_no_user_decisions(app):
    """With no user_decisions, compiler defaults to PDFLATEX and version to TEXLIVE_2025."""
    preflight = {'tex_files': []}
    with app.app_context():
        form = review.ReviewForm(MultiDict(), meta={'csrf': False})
        review._populate_form(form, preflight, None)
        assert form.compiler.data == Compilation.SupportedCompiler.PDFLATEX.value
        assert form.compiler_version.data == Compilation.CompilerVersion.TEXLIVE_2025.value


def _mock_file_store(app, mocker, directives_exist):
    """Wire app.api.get_file_store() to a stub whose does_directives_exist
    returns the given bool."""
    store = MagicMock()
    store.does_directives_exist.return_value = directives_exist
    mocker.patch.object(app.api, 'get_file_store', return_value=store)
    return store


def test_get_notifications_preflight_and_directives(app, mocker):
    """Both preflight present and directives ready: two success notifications."""
    with app.app_context():
        _mock_file_store(app, mocker, directives_exist=True)
        notes = review._get_notifications('sub1', {'tex_files': []})
    titles = [n['title'] for n in notes]
    severities = [n['severity'] for n in notes]
    assert titles == ['Preflight complete', 'Directives ready']
    assert severities == ['success', 'success']


def test_get_notifications_preflight_only(app, mocker):
    """Preflight present, directives missing: complete + pending."""
    with app.app_context():
        _mock_file_store(app, mocker, directives_exist=False)
        notes = review._get_notifications('sub1', {'tex_files': []})
    assert [n['title'] for n in notes] == ['Preflight complete', 'Directives pending']
    assert [n['severity'] for n in notes] == ['success', 'info']


def test_get_notifications_directives_only(app, mocker):
    """No preflight but directives ready: pending warning + success."""
    with app.app_context():
        _mock_file_store(app, mocker, directives_exist=True)
        notes = review._get_notifications('sub1', None)
    assert [n['title'] for n in notes] == ['Preflight pending', 'Directives ready']
    assert [n['severity'] for n in notes] == ['warning', 'success']


def test_get_notifications_nothing_ready(app, mocker):
    """Neither preflight nor directives: two pending notifications."""
    with app.app_context():
        store = _mock_file_store(app, mocker, directives_exist=False)
        notes = review._get_notifications('sub1', None)
    assert [n['title'] for n in notes] == ['Preflight pending', 'Directives pending']
    assert [n['severity'] for n in notes] == ['warning', 'info']
    store.does_directives_exist.assert_called_once_with('sub1')


def test_store_source_format_none_preflight_is_noop(app, mocker):
    """No preflight_data: nothing read, nothing saved."""
    mock_get_lang = mocker.patch.object(review.dm, 'get_lang_from_preflight')
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        review._store_source_format(None, MagicMock(), 'sub1')
    mock_get_lang.assert_not_called()
    mock_save.assert_not_called()


def test_store_source_format_none_lang_is_noop(app, mocker):
    """Preflight present but no detected lang: no save."""
    mocker.patch.object(review.dm, 'get_lang_from_preflight', return_value=None)
    mock_session = mocker.patch.object(review, 'user_and_client_from_session')
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        review._store_source_format({'tex_files': []}, MagicMock(), 'sub1')
    mock_save.assert_not_called()
    mock_session.assert_not_called()


def test_store_source_format_saves_command(app, authorized_user, mocker):
    """Detected lang is saved as SetSourceFormat on the submission."""
    mocker.patch.object(review.dm, 'get_lang_from_preflight', return_value='tex')
    mocker.patch.object(review, 'user_and_client_from_session',
                        return_value=(authorized_user, None))
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        review._store_source_format({'tex_files': []}, MagicMock(), 'sub1')
    mock_save.assert_called_once()
    cmd = mock_save.call_args[0][0]
    assert isinstance(cmd, SetSourceFormat)
    assert cmd.source_format == 'tex'
    assert mock_save.call_args[1] == {'submission_id': 'sub1'}


def test_store_source_format_swallows_save_error(app, authorized_user, mocker, caplog):
    """SaveError from api.save is logged as a warning, not raised."""
    mocker.patch.object(review.dm, 'get_lang_from_preflight', return_value='tex')
    mocker.patch.object(review, 'user_and_client_from_session',
                        return_value=(authorized_user, None))
    with app.app_context():
        mocker.patch.object(app.api, 'save',
                            side_effect=SaveError("boom"))
        review._store_source_format({'tex_files': []}, MagicMock(), 'sub1')
    assert any('Could not save SetSourceFormat for sub1' in r.message
               for r in caplog.records)
