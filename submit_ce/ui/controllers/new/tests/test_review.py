"""Tests for :mod:`submit_ce.ui.controllers.new.review`."""

import re
from http import HTTPStatus as status
from unittest.mock import MagicMock

import pytest
from werkzeug.datastructures import MultiDict

from submit_ce.ui.tests.csrf_util import parse_csrf_token

from submit_ce.domain.compilation import Compilation
from submit_ce.domain.event import SetSourceFormat
from submit_ce.domain.exceptions import InvalidEvent, SaveError
from submit_ce.ui.controllers.new import review


def test_review_files_get_warning_via_http(app, authorized_client, sub_files_tex,
                                           mocker):
    """End-to-end: GET /<id>/review_files triggers flash_warning when
    _load_or_create_preflight yields no preflight data."""
    mocker.patch.object(review, '_load_or_create_preflight',
                        return_value=(None, None))
    mock_flash = mocker.patch.object(review.alerts, 'flash_warning')

    url = f"/{sub_files_tex.submission_id}/review_files"
    resp = authorized_client.get(url)

    assert resp.status_code == status.OK
    assert mock_flash.called
    # Flash text changed when the page was redesigned to show a clearer
    # placeholder instead of bare empty form controls. Assert on the
    # title and a stable substring of the body.
    assert mock_flash.call_args[1].get('title') == 'Preflight unavailable'
    assert "preflight service is temporarily unavailable" in str(
        mock_flash.call_args[0][0])



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
    """GET the review page and pull the CSRF token.

    Stubs preflight + file_notes so the form (including csrf_token)
    actually renders. The Review Files template hides the form (and
    its csrf_token) when file_notes is empty -- see review_files.html.
    Tests that use this helper aren't checking the no-preflight branch,
    they just need a CSRF for a subsequent POST.
    """
    mocker.patch.object(
        review, '_load_or_create_preflight',
        return_value=({'tex_files': [],
                       'detected_toplevel_files': []}, None))
    # file_notes is consumed by the template's group_preflight_files
    # filter, which expects a list of dicts each carrying a 'filename'.
    mocker.patch.object(review.dm, 'get_files_from_preflight',
                        return_value=[{'filename': 'paper.tex'}])
    resp = authorized_client.get(url)
    return parse_csrf_token(resp)


def test_review_files_post_with_changes_redirects_to_parent(
        app, authorized_client, sub_files_tex, mocker):
    """End-to-end POST: when _update_preflight reports changes, the controller
    marks STAGE_PARENT and the flow redirects (303 SEE_OTHER)."""
    url = f"/{sub_files_tex.submission_id}/review_files"
    csrf = _get_csrf(authorized_client, url, mocker)

    mock_update = mocker.patch.object(review, '_update_preflight',
                                      return_value=True)
    mock_load_dir = mocker.patch.object(review, '_load_or_create_directives')

    resp = authorized_client.post(url, data={'csrf_token': csrf, 'action': 'next'})

    assert resp.status_code == status.SEE_OTHER
    mock_update.assert_called_once()
    mock_load_dir.assert_not_called()


def test_review_files_post_no_changes_no_preflight_flashes(
        app, authorized_client, sub_files_tex, mocker):
    """End-to-end POST: when there are no changes but preflight is still
    unavailable, the controller flashes a warning and stays on the stage."""
    url = f"/{sub_files_tex.submission_id}/review_files"
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
        app, authorized_client, sub_files_tex, mocker):
    """End-to-end POST: when there are no changes and preflight is present,
    the controller dispatches a StoreZzrm event (write 00README under the
    submission row lock) and advances to the next stage. [SUBMISSION-205]"""
    url = f"/{sub_files_tex.submission_id}/review_files"
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

    # The 00README write now goes through save() as a StoreZzrm event, not a
    # bare (unlocked) store_zzrm file-store call.
    mock_save = mocker.patch.object(app.api, 'save',
                                    return_value=(MagicMock(), []))

    resp = authorized_client.post(url, data={'csrf_token': csrf, 'action': 'next'})

    assert resp.status_code == status.SEE_OTHER
    fake_zzrm.from_dict.assert_called_once_with({'sources': []})
    fake_zzrm.update_from_preflight.assert_called_once()

    zzrm_calls = [c for c in mock_save.call_args_list
                  if c.args and isinstance(c.args[0], review.StoreZzrm)]
    assert len(zzrm_calls) == 1
    event = zzrm_calls[0].args[0]
    assert event.zzrm == {'merged': True}
    assert zzrm_calls[0].kwargs['submission_id'] == str(sub_files_tex.submission_id)


def test_review_files_post_danger_issue_blocks_continue(
        app, authorized_client, sub_files_tex, mocker):
    """SUBMISSION-216: a danger-severity preflight issue blocks Continue --
    the controller stays on the stage (200, not a 303 redirect), renders the
    'Cannot continue' card, and does not generate directives or store the
    00README."""
    url = f"/{sub_files_tex.submission_id}/review_files"
    csrf = _get_csrf(authorized_client, url, mocker)

    mocker.patch.object(review, '_update_preflight', return_value=False)
    # A real danger payload so the gate and the rendered card agree
    # (conflicting_file_type is a danger code).
    danger_preflight = {
        'tex_files': [],
        'detected_toplevel_files': [
            {'filename': 'main.tex',
             'issues': [{'key': 'conflicting_file_type', 'info': ''}]}],
    }
    mocker.patch.object(review, '_load_or_create_preflight',
                        return_value=(danger_preflight, {'sources': []}))
    mock_load_dir = mocker.patch.object(review, '_load_or_create_directives')
    mock_save = mocker.patch.object(app.api, 'save',
                                    return_value=(MagicMock(), []))

    resp = authorized_client.post(url, data={'csrf_token': csrf, 'action': 'next'})

    assert resp.status_code == status.OK           # stayed; did not advance
    mock_load_dir.assert_not_called()              # no directives generated
    assert b'Cannot continue' in resp.data          # persistent danger card rendered
    assert not any(c.args and isinstance(c.args[0], review.StoreZzrm)
                   for c in mock_save.call_args_list)


def test_review_files_get_auto_checks_only_unused(
        app, authorized_client, sub_files_tex, mocker):
    """SUBMISSION-222: the delete box is pre-checked for UNUSED files
    only. Used and selected-top-level files are disabled and unchecked;
    maybe-used files are enabled but left unchecked (we don't suggest deleting
    something we merely couldn't resolve)."""
    preflight = {
        'detected_toplevel_files': [{'filename': 'main.tex'}],
        'tex_files': [{'filename': 'main.tex', 'used_other_files': ['used.png']}],
        'image_files': [{'filename': 'used.png'}, {'filename': 'orphan.png'}],
        'maybe_used_files': ['guess.pygtex'],
    }
    mocker.patch.object(review, '_load_or_create_preflight',
                        return_value=(preflight, None))
    url = f"/{sub_files_tex.submission_id}/review_files"
    resp = authorized_client.get(url)
    assert resp.status_code == status.OK
    html = resp.data.decode()

    def box(name):
        m = re.search(
            r'<input type="checkbox" name="selected_files" value="%s"[^>]*>'
            % re.escape(name), html)
        assert m, f"no delete checkbox rendered for {name}"
        return m.group(0)

    assert 'checked' in box('orphan.png')                       # unused -> pre-checked
    assert 'disabled' in box('used.png')                        # used -> protected
    assert 'checked' not in box('used.png')
    assert 'disabled' in box('main.tex')                        # top-level -> protected
    assert 'checked' not in box('main.tex')
    assert 'disabled' not in box('guess.pygtex')                # maybe-used -> deletable
    assert 'checked' not in box('guess.pygtex')                 #            -> but not suggested


def test_review_files_get_renders_directory_cascade_checkbox(
        app, authorized_client, sub_files_tex, mocker):
    """SUBMISSION-223 / C3.2: directory rows carry a JS-only cascade checkbox
    whose data-dir is the full path prefix (so the cascade JS matches nested
    file values). The folder control has no `name`, so it is never submitted."""
    preflight = {
        'detected_toplevel_files': [{'filename': 'main.tex'}],
        'tex_files': [{'filename': 'main.tex'}],
        'image_files': [{'filename': 'fig/plot.png'},
                        {'filename': 'fig/deep/x.png'}],
    }
    mocker.patch.object(review, '_load_or_create_preflight',
                        return_value=(preflight, None))
    url = f"/{sub_files_tex.submission_id}/review_files"
    resp = authorized_client.get(url)
    assert resp.status_code == status.OK
    html = resp.data.decode()

    # Nested directory rows get cascade checkboxes with full-path prefixes.
    assert 'class="dir-delete" data-dir="fig/"' in html
    assert 'class="dir-delete" data-dir="fig/deep/"' in html
    # Files render with their full nested paths (what the JS matches against).
    assert 'name="selected_files" value="fig/plot.png"' in html
    assert 'name="selected_files" value="fig/deep/x.png"' in html
    # The folder control is a UI-only toggle: it must not be a submitted field.
    assert re.search(r'class="dir-delete"[^>]*\bname=', html) is None


def test_review_files_get_renders_multiple_top_level_selectors(
        app, authorized_client, sub_files_tex, mocker):
    """SUBMISSION-226: persisted multiple top-levels render as ordered
    `top_level_tex_files[]` dropdowns, each preselected, built from the candidate
    tex-file list; the field exposes the candidate count for the add cap."""
    preflight = {
        'detected_toplevel_files': [{'filename': 'a.tex'}],
        'tex_files': [{'filename': 'a.tex'}, {'filename': 'b.tex'},
                      {'filename': 'c.tex'}],
    }
    decisions = {'sources': [{'filename': 'b.tex'}, {'filename': 'a.tex'}]}
    mocker.patch.object(review, '_load_or_create_preflight',
                        return_value=(preflight, decisions))
    url = f"/{sub_files_tex.submission_id}/review_files"
    resp = authorized_client.get(url)
    assert resp.status_code == status.OK
    html = resp.data.decode()

    selects = re.findall(
        r'<select name="top_level_tex_files\[\]"[^>]*>(.*?)</select>', html, re.S)
    assert len(selects) == 2                                   # one per top-level
    assert re.search(r'<option value="b.tex" selected>', selects[0])   # order kept
    assert re.search(r'<option value="a.tex" selected>', selects[1])
    assert 'data-candidate-count="3"' in html                 # a/b/c candidates
    assert 'id="tl-add"' in html


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


def test_ordered_top_level_filenames_reads_sources_in_order():
    """SUBMISSION-170: ordered, de-duped filenames from persisted sources."""
    ud = {'sources': [{'filename': 'b.tex'}, {'filename': 'a.tex'},
                      {'filename': 'b.tex'}]}
    assert review._ordered_top_level_filenames(ud) == ['b.tex', 'a.tex']
    assert review._ordered_top_level_filenames(None) == []
    assert review._ordered_top_level_filenames({}) == []
    assert review._ordered_top_level_filenames({'sources': []}) == []


def test_update_preflight_persists_ordered_multiple_top_levels(
        app, authorized_user, mocker):
    """SUBMISSION-170: all selected top-levels persist as an ordered
    `sources` list (via top_level_tex_files[]), not just `source_file`."""
    mocker.patch.object(review, '_get_user_decisions_data', return_value=None)
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        params = MultiDict([
            ('top_level_tex_files[]', 'a.tex'),
            ('top_level_tex_files[]', 'b.tex'),
            ('compiler', 'pdflatex'),
            ('compiler_version', '2025'),
        ])
        review._update_preflight(
            params, 'sub1', _make_workspace('a.tex', 'b.tex'),
            authorized_user, None,
        )
    mock_save.assert_called_once()
    cmd = mock_save.call_args[0][0]
    assert cmd.decisions['sources'] == [{'filename': 'a.tex'}, {'filename': 'b.tex'}]


def test_update_preflight_preserves_top_level_order(app, authorized_user, mocker):
    """Reordering the selection persists the new order (B before A)."""
    mocker.patch.object(review, '_get_user_decisions_data', return_value=None)
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        params = MultiDict([
            ('top_level_tex_files[]', 'b.tex'),
            ('top_level_tex_files[]', 'a.tex'),
            ('compiler', 'pdflatex'),
            ('compiler_version', '2025'),
        ])
        review._update_preflight(
            params, 'sub1', _make_workspace('a.tex', 'b.tex'),
            authorized_user, None,
        )
    cmd = mock_save.call_args[0][0]
    assert cmd.decisions['sources'] == [{'filename': 'b.tex'}, {'filename': 'a.tex'}]


def test_update_preflight_single_source_file_unchanged_shape(
        app, authorized_user, mocker):
    """Single-dropdown UI (source_file only) still persists a one-item sources
    list -- is a no-op for the current UI."""
    mocker.patch.object(review, '_get_user_decisions_data', return_value=None)
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        params = MultiDict([
            ('source_file', 'main.tex'),
            ('compiler', 'pdflatex'),
            ('compiler_version', '2025'),
        ])
        review._update_preflight(
            params, 'sub1', _make_workspace('main.tex'),
            authorized_user, None,
        )
    cmd = mock_save.call_args[0][0]
    assert cmd.decisions['sources'] == [{'filename': 'main.tex'}]


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
    # G29/SUBMISSION-215: a selection-only change still saves SetDecisions, but
    # preflight is NOT invalidated (no file deleted), so this now returns False.
    assert result is False
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
    # G29/SUBMISSION-215: decisions saved, but no deletion -> preflight not
    # invalidated -> returns False.
    assert result is False
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


def test_selected_top_level_files_dedupes_and_orders():
    """_selected_top_level_files reads source_file + top_level_tex_files[],
    de-duped and order-preserving (SUBMISSION-209)."""
    params = MultiDict([
        ('source_file', 'a.tex'),
        ('top_level_tex_files[]', 'b.tex'),
        ('top_level_tex_files[]', 'a.tex'),
        ('top_level_tex_files[]', ''),
    ])
    assert review._selected_top_level_files(params) == ['a.tex', 'b.tex']


def test_update_preflight_protects_selected_top_level_file(
        app, authorized_user, mocker):
    """A file that is the selected top-level TeX file is filtered out of the
    deletion set and the user is warned; other deletions proceed (SUBMISSION-209)."""
    mocker.patch.object(review, '_get_user_decisions_data', return_value=None)
    mock_flash = mocker.patch.object(review.alerts, 'flash_warning')
    with app.app_context():
        mock_save = mocker.patch.object(app.api, 'save')
        params = MultiDict([
            ('source_file', 'main.tex'),
            ('compiler', 'pdflatex'),
            ('compiler_version', '2025'),
            ('selected_files', 'main.tex'),
            ('selected_files', 'junk.tex'),
        ])
        result = review._update_preflight(
            params, 'sub1', _make_workspace('main.tex', 'junk.tex'),
            authorized_user, None,
        )
    assert result is True
    mock_flash.assert_called_once()
    cmd = mock_save.call_args[0][0]
    assert 'main.tex' not in cmd.files_to_delete
    assert cmd.files_to_delete == ['junk.tex']


def test_update_preflight_no_warning_when_top_level_not_marked(
        app, authorized_user, mocker):
    """When the selected top-level isn't marked for deletion, no warning fires."""
    mocker.patch.object(review, '_get_user_decisions_data', return_value=None)
    mock_flash = mocker.patch.object(review.alerts, 'flash_warning')
    with app.app_context():
        mocker.patch.object(app.api, 'save')
        params = MultiDict([
            ('source_file', 'main.tex'),
            ('compiler', 'pdflatex'),
            ('compiler_version', '2025'),
            ('selected_files', 'junk.tex'),
        ])
        review._update_preflight(
            params, 'sub1', _make_workspace('main.tex', 'junk.tex'),
            authorized_user, None,
        )
    mock_flash.assert_not_called()


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
