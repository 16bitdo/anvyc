"""anvyc config projects <verb> CLI 동작 테스트."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def test_projects_list_json(tmp_path: Path) -> None:
    proj = tmp_path / "x"
    (proj / ".git").mkdir(parents=True)
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text(f"projects:\n  - {proj}\nexclude_projects:\n  - ~/dev/gone\n")
    result = runner.invoke(
        app, ["config", "projects", "list", "--config", str(cfg), "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["includes"][0]["exists"] is True
    assert data["excludes"][0]["path"] == "~/dev/gone"


def test_projects_list_empty(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    result = runner.invoke(app, ["config", "projects", "list", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "없음" in result.stdout or "없습니다" in result.stdout


def test_projects_add_and_rm(tmp_path: Path) -> None:
    proj = tmp_path / "x"
    (proj / ".git").mkdir(parents=True)
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    r1 = runner.invoke(app, ["config", "projects", "add", str(proj), "--config", str(cfg)])
    assert r1.exit_code == 0
    assert "added" in r1.stdout.lower() or "추가" in r1.stdout
    written = yaml.safe_load(cfg.read_text())["projects"]
    assert any(str(proj) in w or w.startswith("~") for w in written)
    r2 = runner.invoke(app, ["config", "projects", "rm", str(proj), "--config", str(cfg)])
    assert r2.exit_code == 0
    assert "projects" not in (yaml.safe_load(cfg.read_text()) or {})


def test_projects_exclude_and_unexclude(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    r1 = runner.invoke(app, ["config", "projects", "exclude", "~/dev/archived", "--config", str(cfg)])
    assert r1.exit_code == 0
    assert yaml.safe_load(cfg.read_text())["exclude_projects"] == ["~/dev/archived"]
    r2 = runner.invoke(app, ["config", "projects", "unexclude", "~/dev/archived", "--config", str(cfg)])
    assert r2.exit_code == 0
    assert "exclude_projects" not in (yaml.safe_load(cfg.read_text()) or {})
