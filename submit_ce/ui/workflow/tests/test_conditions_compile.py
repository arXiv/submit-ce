"""Tests for :func:`conditions.has_compiled_current_source` (SUBMISSION-75).

The Process stage uses this predicate to decide whether compilation must be
(re)initiated on arrival. A compile counts only if no file-change event has
occurred since the most recent ``StartCompileSource`` -- any file change
invalidates the prior compile and its artifacts.
"""

from datetime import datetime

from pytz import UTC

from submit_ce.domain import agent, submission as submod
from submit_ce.domain.event.file import RemoveAllFiles, UploadFiles
from submit_ce.domain.event.process import StartCompileSource, StartPreflight
from submit_ce.ui.workflow import conditions


def _user(uid: str = "u1") -> agent.PublicUser:
    return agent.PublicUser(name="Test User", user_id=uid,
                            email=f"{uid}@example.org", endorsements=[])


def _submission() -> submod.Submission:
    u = _user()
    return submod.Submission(creator=u, owner=u, created=datetime.now(UTC))


def _upload() -> UploadFiles:
    return UploadFiles(creator=_user(), files=[])


def _compile() -> StartCompileSource:
    return StartCompileSource(creator=_user(), source_content_id="x")


def test_no_events_means_no_current_compile():
    """A brand-new submission has never compiled -> compile is needed."""
    assert conditions.has_compiled_current_source(_submission(), []) is False


def test_compile_without_later_file_change_is_current():
    """Upload then compile, nothing after -> the compile is current."""
    events = [_upload(), _compile()]
    assert conditions.has_compiled_current_source(_submission(), events) is True


def test_file_change_after_compile_invalidates_it():
    """A file change after the last compile means the source moved on."""
    events = [_upload(), _compile(), _upload()]
    assert conditions.has_compiled_current_source(_submission(), events) is False


def test_remove_all_after_compile_invalidates_it():
    """RemoveAllFiles is a file-change event and invalidates the compile."""
    events = [_upload(), _compile(), RemoveAllFiles(creator=_user())]
    assert conditions.has_compiled_current_source(_submission(), events) is False


def test_recompile_after_change_is_current_again():
    """Change then recompile -> current once more (latest compile wins)."""
    events = [_upload(), _compile(), _upload(), _compile()]
    assert conditions.has_compiled_current_source(_submission(), events) is True


def test_non_file_events_after_compile_do_not_invalidate():
    """Only file-change events invalidate; e.g. a preflight run does not."""
    events = [_upload(), _compile(), StartPreflight(creator=_user())]
    assert conditions.has_compiled_current_source(_submission(), events) is True
