"""Tests for the finalize-time QA source-package rebuild. [SUBMISSION-205]

The QA snapshot (``get_qa_artifact_info``) references the persisted
``<id>.tar.gz`` directly and never builds one, so finalize must rebuild it
under the lock (via ``BuildSourcePackage``) before the snapshot is taken --
otherwise QA ships a stale or missing source package.
"""

from unittest.mock import MagicMock

from submit_ce.domain import agent
from submit_ce.ui.controllers.new import final
from submit_ce.domain.event.process import BuildSourcePackage
from submit_ce.ui.config import settings


def _creator(uid="u1"):
    # A real agent -- BuildSourcePackage validates creator/client as
    # pydantic discriminated unions, so a bare MagicMock won't construct.
    return agent.PublicUser(name="Test User", user_id=uid,
                            email=f"{uid}@example.org", endorsements=[])


def test_rebuild_dispatches_build_source_package_when_qa_enabled(app, mocker):
    """With QA upload enabled, a BuildSourcePackage is dispatched via save()."""
    mock_save = mocker.patch.object(app.api, 'save',
                                    return_value=(MagicMock(), []))
    mocker.patch.object(settings, 'QA_GS_UPLOAD_ENABLED', True)
    mocker.patch.object(settings, 'QA_PUBSUB_ENABLED', False)

    with app.app_context():
        final._rebuild_source_package_for_qa('123', _creator(), None)

    build_calls = [c for c in mock_save.call_args_list
                   if c.args and isinstance(c.args[0], BuildSourcePackage)]
    assert len(build_calls) == 1
    assert build_calls[0].kwargs['submission_id'] == '123'


def test_rebuild_skips_when_qa_disabled(app, mocker):
    """With both QA paths disabled, no rebuild is dispatched."""
    mock_save = mocker.patch.object(app.api, 'save')
    mocker.patch.object(settings, 'QA_GS_UPLOAD_ENABLED', False)
    mocker.patch.object(settings, 'QA_PUBSUB_ENABLED', False)

    with app.app_context():
        final._rebuild_source_package_for_qa('123', _creator(), None)

    mock_save.assert_not_called()


def test_rebuild_swallows_errors(app, mocker):
    """A rebuild failure must never propagate out of finalize."""
    mocker.patch.object(app.api, 'save', side_effect=RuntimeError("boom"))
    mocker.patch.object(settings, 'QA_GS_UPLOAD_ENABLED', True)
    mocker.patch.object(settings, 'QA_PUBSUB_ENABLED', True)

    with app.app_context():
        # Must not raise even though save() blows up.
        final._rebuild_source_package_for_qa('123', _creator(), None)
