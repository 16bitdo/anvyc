# tests/unit/test_guard_targets.py
from pathlib import Path

import pytest

from anvyc.core.guard_targets import resolve_guard_targets


def test_guard_honors_individual_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    indiv = tmp_path / "proj"
    (indiv / ".git").mkdir(parents=True)
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(empty),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    targets = resolve_guard_targets(None, None)
    assert indiv.resolve() in targets


def test_guard_explicit_project_unchanged(tmp_path: Path) -> None:
    indiv = tmp_path / "p"
    (indiv / ".git").mkdir(parents=True)
    assert resolve_guard_targets([indiv], None) == [indiv.resolve()]
