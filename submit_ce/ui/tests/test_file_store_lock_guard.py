"""Guard test: every direct file_store mutation in UI controllers must
happen inside `with api.lock_submission(...)`.

This is a structural check. Direct file-store writes/deletes bypass
`api.save()` and so do not pick up the row lock that `save()` would
take. Without the wrapper, two browsers on the same submission can
race a write against an in-flight compile/preflight/directives.

The check targets only `submit_ce/ui/controllers/**.py`. It does NOT
target:

- `submit_ce/domain/event/file.py` and other event-side mutators,
  which run inside `event.execute()` already covered by `save()`'s
  lock.
- `submit_ce/implementations/compile/compile_api_service.py`, whose
  `store_preview`-style writes happen inside `start_compile` /
  `start_preflight` invoked from `Start*.execute()`, again under
  `save()`.
- Test code and the file_store implementations themselves.

A naive regex would miss aliased / fluent forms. The check uses an
AST walk that tracks names assigned from `*.get_file_store()` and
also recognises the fluent `*.get_file_store().store_*(...)` form.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, Set

import pytest


CONTROLLERS_ROOT = (
    Path(__file__).resolve().parents[2] / "ui" / "controllers"
)

# Conventional aliases for the file store. Calls on a name matching
# one of these are tracked even if we can't see the assignment (e.g.
# the alias was set in an enclosing scope or passed in as a parameter).
CONVENTIONAL_NAMES: Set[str] = {"file_store", "fstore", "store"}


def _iter_controller_files() -> Iterable[Path]:
    for path in CONTROLLERS_ROOT.rglob("*.py"):
        # Skip the controllers' own test subdir and __pycache__.
        parts = set(path.parts)
        if "tests" in parts or "__pycache__" in parts:
            continue
        yield path


def _attach_parents(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node  # type: ignore[attr-defined]


def _is_file_store_factory_call(node: ast.AST) -> bool:
    """True if `node` is a Call whose .func is an Attribute with
    attr == 'get_file_store' (e.g. `current_app.api.get_file_store()`,
    `api.get_file_store()`, `self.api.get_file_store()`)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get_file_store"
    )


def _collect_aliases(scope: ast.AST) -> Set[str]:
    """Names within `scope` assigned (somewhere) from `*.get_file_store()`."""
    aliases: Set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and _is_file_store_factory_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases.add(target.id)
        elif isinstance(node, ast.AnnAssign) and _is_file_store_factory_call(node.value):
            if isinstance(node.target, ast.Name):
                aliases.add(node.target.id)
    return aliases


def _is_tracked_receiver(receiver: ast.AST, aliases: Set[str]) -> bool:
    if isinstance(receiver, ast.Name) and (
        receiver.id in aliases or receiver.id in CONVENTIONAL_NAMES
    ):
        return True
    if _is_file_store_factory_call(receiver):
        return True
    return False


def _inside_lock_submission_with(node: ast.AST) -> bool:
    """Walk parent links to see if `node` is inside a `with` block
    whose context manager is a Call of an Attribute with
    attr == 'lock_submission'."""
    current = getattr(node, "parent", None)
    while current is not None:
        if isinstance(current, (ast.With, ast.AsyncWith)):
            for item in current.items:
                ctx = item.context_expr
                if (
                    isinstance(ctx, ast.Call)
                    and isinstance(ctx.func, ast.Attribute)
                    and ctx.func.attr == "lock_submission"
                ):
                    return True
        current = getattr(current, "parent", None)
    return False


def _find_violations(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    _attach_parents(tree)
    aliases = _collect_aliases(tree)

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if not (func.attr.startswith("store_") or func.attr.startswith("delete_")):
            continue
        if not _is_tracked_receiver(func.value, aliases):
            continue
        if _inside_lock_submission_with(node):
            continue
        violations.append(
            f"{path}:{node.lineno}: {ast.unparse(node)}"
        )
    return violations


def test_ui_controller_file_store_mutations_are_locked():
    """Every file_store.store_*/delete_* call in a UI controller must
    be wrapped in `with api.lock_submission(...)`."""
    all_violations: list[str] = []
    for path in _iter_controller_files():
        all_violations.extend(_find_violations(path))

    assert not all_violations, (
        "Direct file_store mutations in UI controllers must be inside "
        "`with api.lock_submission(submission_id):`. Found:\n  "
        + "\n  ".join(all_violations)
    )


def test_guard_does_not_fire_on_event_side_mutators(tmp_path: Path):
    """Negative control: the same patterns in domain/event/file.py
    are covered by api.save()'s lock and must not be flagged.

    We assert this by running the guard's checker over that file
    directly and verifying it returns no violations only because the
    file is not under the controllers root — i.e. the guard's scope
    excludes it by construction."""
    event_file = (
        Path(__file__).resolve().parents[2]
        / "domain" / "event" / "file.py"
    )
    assert event_file.exists(), "expected domain/event/file.py to exist"
    # The file is not under CONTROLLERS_ROOT, so the controller walk
    # skips it. _find_violations would flag every call site if applied
    # directly — that's the point: scope, not behaviour, exempts it.
    assert CONTROLLERS_ROOT not in event_file.parents


def test_guard_catches_a_synthetic_ungated_mutation(tmp_path: Path):
    """Positive control: synthesise an ungated mutation in a fake
    controller file and verify the checker reports it."""
    fake = tmp_path / "fake_controller.py"
    fake.write_text(
        "from flask import current_app\n"
        "def handler(submission_id):\n"
        "    file_store = current_app.api.get_file_store()\n"
        "    file_store.delete_source_file(submission_id, 'main.tex')\n"
    )
    violations = _find_violations(fake)
    assert any("delete_source_file" in v for v in violations), violations


def test_guard_accepts_wrapped_mutation(tmp_path: Path):
    """Positive control: same mutation wrapped in `lock_submission`
    must not be flagged."""
    fake = tmp_path / "fake_controller_ok.py"
    fake.write_text(
        "from flask import current_app\n"
        "def handler(submission_id):\n"
        "    api = current_app.api\n"
        "    file_store = api.get_file_store()\n"
        "    with api.lock_submission(submission_id):\n"
        "        file_store.delete_source_file(submission_id, 'main.tex')\n"
    )
    violations = _find_violations(fake)
    assert violations == [], violations


def test_guard_handles_fluent_chain(tmp_path: Path):
    """Fluent call current_app.api.get_file_store().delete_directives(...)
    outside of a lock_submission block must be flagged."""
    fake = tmp_path / "fake_controller_fluent.py"
    fake.write_text(
        "from flask import current_app\n"
        "def handler(submission_id):\n"
        "    current_app.api.get_file_store().delete_directives(submission_id)\n"
    )
    violations = _find_violations(fake)
    assert any("delete_directives" in v for v in violations), violations
