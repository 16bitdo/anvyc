# tests/unit/test_mcp_project_list_scope.py
"""MCP project_list 가 projects/exclude_projects 를 honoring 하는지."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_mcp_project_list_honors_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    container = tmp_path / "dev"
    (container / "p1" / ".git").mkdir(parents=True)
    indiv = tmp_path / "work" / "x"
    (indiv / ".git").mkdir(parents=True)
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(container),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    from anvyc.mcp.server import _dispatch

    result = _dispatch("project_list", {})  # roots 미지정 → iter_project_dirs
    names = {Path(e["path"]).name for e in result}
    assert "p1" in names and "x" in names
