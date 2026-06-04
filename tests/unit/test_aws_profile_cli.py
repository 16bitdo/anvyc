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


def test_show_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "show", "ws-dev", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["name"] == "ws-dev"
    assert data["auth_method"] == "sso"
    assert data["sso_session"] == "ws"


def test_show_unknown_profile_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "show", "ghost"])
    assert result.exit_code == 1
    assert "ghost" in result.stdout


def test_list_probe_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    from anvyc.core import aws_probe

    def fake_probe(profile: str, **_k: object) -> aws_probe.ProbeResult:
        return aws_probe.ProbeResult(ok=True, account="123456789012", arn="arn:aws:iam::1:role/r")

    monkeypatch.setattr(aws_probe, "probe_caller_identity", fake_probe)
    result = runner.invoke(app, ["aws", "profile", "list", "--probe", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert all(p["probe"]["ok"] is True for p in data["profiles"])
    assert data["profiles"][0]["probe"]["account"] == "123456789012"


def test_list_no_status_json_shape_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # --no-status JSON 도 전체 키를 포함해야 함 (KeyError 회피).
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "list", "--no-status", "--json"])
    assert result.exit_code == 0
    for p in json.loads(result.stdout)["profiles"]:
        assert set(p.keys()) == {"name", "auth_method", "status", "sso_session", "expires_at", "probe"}


def test_show_human(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "show", "ws-dev"])
    assert result.exit_code == 0
    assert "ws-dev" in result.stdout
    assert "sso_session" in result.stdout  # profile 키가 출력됨


def test_create_writes_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    result = runner.invoke(
        app,
        ["aws", "profile", "create", "newp", "--region", "ap-northeast-2", "--yes"],
    )
    assert result.exit_code == 0
    text = (tmp_path / ".aws" / "config").read_text(encoding="utf-8")
    assert "[profile newp]" in text and "region = ap-northeast-2" in text


def test_create_dry_run_no_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text("[profile a]\nregion = x\n", encoding="utf-8")
    result = runner.invoke(
        app, ["aws", "profile", "create", "b", "--region", "y", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "[profile b]" not in (tmp_path / ".aws" / "config").read_text(encoding="utf-8")


def test_create_existing_errors_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text("[profile dup]\nregion = x\n", encoding="utf-8")
    result = runner.invoke(
        app, ["aws", "profile", "create", "dup", "--region", "y", "--yes"]
    )
    assert result.exit_code == 1
    assert "이미 존재" in result.stdout


def test_create_confirm_abort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    result = runner.invoke(
        app, ["aws", "profile", "create", "p", "--region", "y"], input="n\n"
    )
    assert result.exit_code == 0
    assert not (tmp_path / ".aws" / "config").exists() or "[profile p]" not in (
        tmp_path / ".aws" / "config"
    ).read_text(encoding="utf-8")


def test_edit_sets_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text(
        "[profile dev]\nregion = us-east-1\n", encoding="utf-8"
    )
    result = runner.invoke(
        app, ["aws", "profile", "edit", "dev", "--set", "region=ap-northeast-2", "--yes"]
    )
    assert result.exit_code == 0
    assert "region = ap-northeast-2" in (tmp_path / ".aws" / "config").read_text(encoding="utf-8")


def test_edit_rejects_static_key_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text("[profile dev]\nregion = x\n", encoding="utf-8")
    result = runner.invoke(
        app, ["aws", "profile", "edit", "dev", "--set", "aws_access_key_id=AKIA_X", "--yes"]
    )
    assert result.exit_code == 1
    assert "정적 자격 키" in result.stdout


def test_edit_missing_profile_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text("[profile dev]\nregion = x\n", encoding="utf-8")
    result = runner.invoke(
        app, ["aws", "profile", "edit", "ghost", "--set", "region=y", "--yes"]
    )
    assert result.exit_code == 1
