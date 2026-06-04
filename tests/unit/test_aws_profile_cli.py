"""anvyc aws profile list/show CLI."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def _home(tmp_path: Path) -> Path:
    aws = tmp_path / ".aws"
    aws.mkdir(parents=True)
    (aws / "config").write_text(
        "[profile ws-dev]\nregion = ap-northeast-2\nsso_session = ws\n\n"
        "[sso-session ws]\nsso_start_url = https://u/start\n\n"
        "[profile legacy]\nregion = us-east-1\n",
        encoding="utf-8",
    )
    (aws / "credentials").write_text("[legacy]\naws_access_key_id = AKIA_X\n", encoding="utf-8")
    return tmp_path


def test_list_human(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "list"])
    assert result.exit_code == 0
    assert "ws-dev" in result.stdout
    assert "legacy" in result.stdout


def test_list_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    names = {p["name"]: p for p in data["profiles"]}
    assert names["ws-dev"]["auth_method"] == "sso"
    assert names["legacy"]["auth_method"] == "static"


def test_list_no_status_skips_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "list", "--no-status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["profiles"][0]["status"] is None
