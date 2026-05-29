"""`anvyc extras` 명령 검증 (step 3).

JSON schema / 표 렌더 / --check exit code 를 검증한다. FORCE_COLOR 환경 무관하게
안정적이도록 표 비교는 ANSI strip 후, --check 경로는 collect_extras_status 를
monkeypatch 해 결정적으로 확인한다.
"""

from __future__ import annotations

import json as jsonlib
import re

import pytest
from typer.testing import CliRunner

import anvyc.cli as cli
from anvyc.cli import app

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_extras_json_schema() -> None:
    result = CliRunner().invoke(app, ["extras", "--json"])
    assert result.exit_code == 0, result.output
    rows = jsonlib.loads(result.output)
    assert isinstance(rows, list) and rows
    names = {r["name"] for r in rows}
    assert {"sops", "age", "op", "mcp", "boto3"} <= names
    for r in rows:
        assert {"name", "kind", "installed", "purpose", "install_cmd"} <= set(r)
        assert isinstance(r["installed"], bool)


def test_extras_table_renders() -> None:
    result = CliRunner().invoke(app, ["extras"])
    assert result.exit_code == 0, result.output
    out = _ANSI.sub("", result.output)
    assert "동반 도구" in out
    assert "SOPS" in out
    # 종류 열 라벨.
    assert "pip extra" in out
    # install_cmd 의 'anvyc[...]' 대괄호가 rich 마크업으로 삼켜지지 않고 보존돼야 한다.
    assert "anvyc[" in out


def test_extras_missing_filter_runs() -> None:
    result = CliRunner().invoke(app, ["extras", "--missing"])
    assert result.exit_code == 0, result.output


def _fake_rows(*, git_installed: bool) -> list[dict[str, object]]:
    return [
        {
            "name": "git",
            "kind": "binary",
            "label": "Git",
            "purpose": "x",
            "installed": git_installed,
            "version": None,
            "install_cmd": "brew install git",
            "install_url": None,
            "pip_extra": None,
            "required": True,
            "platform": None,
            "relevant": True,
        }
    ]


def test_check_passes_when_required_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "collect_extras_status", lambda: _fake_rows(git_installed=True))
    result = CliRunner().invoke(app, ["extras", "--check"])
    assert result.exit_code == 0, result.output


def test_check_fails_when_required_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "collect_extras_status", lambda: _fake_rows(git_installed=False))
    result = CliRunner().invoke(app, ["extras", "--check"])
    assert result.exit_code == 1
