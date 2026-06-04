"""anvyc project list 가 projects/exclude_projects 를 honoring 하는지."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def test_project_list_honors_projects_and_excludes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    container = tmp_path / "dev"
    (container / "p1" / ".git").mkdir(parents=True)
    (container / "p2" / ".git").mkdir(parents=True)
    indiv = tmp_path / "work" / "x"
    (indiv / ".git").mkdir(parents=True)
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text(
        f"project_roots:\n  - {container}\nprojects:\n  - {indiv}\n"
        f"exclude_projects:\n  - {container / 'p2'}\n"
    )
    # project list 는 전역 config 를 load — HOME 을 tmp 로 돌려 이 cfg 가 잡히게
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".anvyc").mkdir()
    (tmp_path / ".anvyc" / "anvyc.yaml").write_text(cfg.read_text())
    result = runner.invoke(app, ["project", "list", "--json"])
    assert result.exit_code == 0
    paths = {Path(e["path"]).name for e in json.loads(result.stdout)}
    assert "p1" in paths and "x" in paths and "p2" not in paths
