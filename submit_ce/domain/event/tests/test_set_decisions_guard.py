"""Tests for the ``SetDecisions`` delete guard. [SUBMISSION-209]

The guard: ``SetDecisions.execute`` must never delete a file listed as a
top-level source in ``decisions`` -- that's the file(s) we're about to
compile -- even if it appears in ``files_to_delete``. This is the
authoritative check; it runs under the submission row lock taken by
``save()``. Exercised directly with a hand-rolled fake store, matching the
style of ``test_store_zzrm.py``.
"""

from datetime import datetime

from pytz import UTC

from submit_ce.domain import submission as submod, agent
from submit_ce.domain.event.process import (
    SetDecisions,
    _protected_top_level_sources,
)


class _FakeFile:
    def __init__(self, nbytes):
        self.bytes = nbytes


class _FakeStore:
    def __init__(self):
        self.deleted = []
        self.user_decisions = None
        self.preflight_deleted = False
        self.directives_deleted = False

    def delete_preflight(self, sid):
        self.preflight_deleted = True

    def delete_directives(self, sid):
        self.directives_deleted = True

    def store_user_decisions(self, sid, decisions):
        self.user_decisions = decisions

    def delete_source_file(self, sid, path):
        self.deleted.append(path)
        return _FakeFile(10)


class _FakeApi:
    def __init__(self):
        self._store = _FakeStore()

    def get_file_store(self):
        return self._store


def _user(uid="u1"):
    return agent.PublicUser(name="Test User", user_id=uid,
                            email=f"{uid}@example.org", endorsements=[])


def _submission(sid="1234567"):
    u = _user()
    s = submod.Submission(creator=u, owner=u, created=datetime.now(UTC))
    s.submission_id = sid
    return s


def test_execute_skips_selected_top_level_file():
    """A top-level source is never deleted; siblings still are."""
    s = _submission()
    api = _FakeApi()
    e = SetDecisions(
        creator=s.creator,
        decisions={'sources': [{'filename': 'main.tex', 'usage': 'toplevel'}]},
        files_to_delete=['main.tex', 'junk.tex'],
    )
    e.execute(api, s)
    assert 'main.tex' not in api._store.deleted
    assert api._store.deleted == ['junk.tex']


def test_execute_protects_source_without_explicit_usage():
    """The Review Files form lists sources without a usage; treat as toplevel."""
    s = _submission()
    api = _FakeApi()
    e = SetDecisions(
        creator=s.creator,
        decisions={'sources': [{'filename': 'main.tex'}]},
        files_to_delete=['main.tex'],
    )
    e.execute(api, s)
    assert api._store.deleted == []
    assert e.bytes_removed == 0


def test_execute_deletes_non_toplevel_and_counts_bytes():
    """Non-top-level files are deleted and their bytes counted."""
    s = _submission()
    api = _FakeApi()
    e = SetDecisions(
        creator=s.creator,
        decisions={'sources': [{'filename': 'main.tex'}]},
        files_to_delete=['fig.png', 'old.bbl'],
    )
    e.execute(api, s)
    assert api._store.deleted == ['fig.png', 'old.bbl']
    assert e.bytes_removed == 20


def test_protected_top_level_sources_helper():
    """toplevel + usage-less sources are protected; include/ignore are not."""
    decisions = {'sources': [
        {'filename': 'a.tex', 'usage': 'toplevel'},
        {'filename': 'b.tex'},                       # no usage -> protected
        {'filename': 'c.sty', 'usage': 'include'},   # not protected
        {'filename': 'd.bib', 'usage': 'ignore'},    # not protected
        {'usage': 'toplevel'},                       # no filename -> ignored
    ]}
    assert _protected_top_level_sources(decisions) == {'a.tex', 'b.tex'}
    assert _protected_top_level_sources({}) == set()
    assert _protected_top_level_sources({'sources': []}) == set()


# --- G29 / SUBMISSION-215: preflight is invalidated only on a file-set change ---

def test_execute_selection_only_keeps_preflight():
    """Selection-only change (no deletions): preflight is preserved, but directives
    are dropped (so they regenerate) and the decisions are persisted."""
    s = _submission()
    api = _FakeApi()
    e = SetDecisions(
        creator=s.creator,
        decisions={'sources': [{'filename': 'main.tex'}],
                   'process': {'compiler': 'pdflatex'}},
        files_to_delete=[],
    )
    e.execute(api, s)
    assert api._store.preflight_deleted is False   # <-- the G29 fix
    assert api._store.directives_deleted is True
    assert api._store.user_decisions is not None
    assert api._store.deleted == []


def test_execute_file_deletion_invalidates_preflight():
    """Deleting a file DOES invalidate preflight (and drops directives)."""
    s = _submission()
    api = _FakeApi()
    e = SetDecisions(
        creator=s.creator,
        decisions={'sources': [{'filename': 'main.tex'}]},
        files_to_delete=['fig.png'],
    )
    e.execute(api, s)
    assert api._store.preflight_deleted is True
    assert api._store.directives_deleted is True
    assert api._store.deleted == ['fig.png']
