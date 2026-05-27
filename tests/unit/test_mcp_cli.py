"""CLI e2e tests for `anvyc mcp install/uninstall/status` (PR A)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anvyc.cli import app
from anvyc.core.mcp_setup import ANVYC_MCP_ARGS, ANVYC_MCP_COMMAND, ANVYC_MCP_KEY


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`Path.home()` 을 tmp_path/home 으로 monkeypatch."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return home


def test_status_both_missing(fake_home: Path) -> None:
    """양쪽 IDE 디렉터리가 없을 때 status — `missing` 라인 2건."""
    result = CliRunner().invoke(app, ["mcp", "status"])
    assert result.exit_code == 0
    # rich.Table 표 헤더 + 본문 — 양쪽 IDE 모두 표시
    assert "claude" in result.stdout
    assert "cursor" in result.stdout
    assert "missing" in result.stdout


def test_status_json(fake_home: Path) -> None:
    result = CliRunner().invoke(app, ["mcp", "status", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 2
    assert {r["ide"] for r in payload} == {"claude", "cursor"}
    assert all(r["has_anvyc"] is False for r in payload)


def test_install_dry_run_no_writes(fake_home: Path) -> None:
    result = CliRunner().invoke(app, ["mcp", "install", "--ide", "cursor"])
    assert result.exit_code == 0
    assert "dry-run" in result.stdout
    # 파일 안 만들어졌는지
    assert not (fake_home / ".cursor" / "mcp.json").is_file()


def test_install_apply_creates_file(fake_home: Path) -> None:
    result = CliRunner().invoke(
        app, ["mcp", "install", "--ide", "cursor", "--apply", "--yes"]
    )
    assert result.exit_code == 0
    cfg = fake_home / ".cursor" / "mcp.json"
    assert cfg.is_file()
    data = json.loads(cfg.read_text())
    assert data["mcpServers"][ANVYC_MCP_KEY] == {
        "command": ANVYC_MCP_COMMAND,
        "args": list(ANVYC_MCP_ARGS),
    }
    assert "IDE 재시작" in result.stdout


def test_install_apply_preserves_existing(fake_home: Path) -> None:
    """기존 다른 server entry 보존."""
    (fake_home / ".cursor").mkdir()
    cfg = fake_home / ".cursor" / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"context7": {"command": "npx", "args": ["context7"]}}}))

    result = CliRunner().invoke(
        app, ["mcp", "install", "--ide", "cursor", "--apply", "--yes"]
    )
    assert result.exit_code == 0
    data = json.loads(cfg.read_text())
    assert set(data["mcpServers"].keys()) == {"context7", ANVYC_MCP_KEY}


def test_uninstall_preserves_others(fake_home: Path) -> None:
    (fake_home / ".cursor").mkdir()
    cfg = fake_home / ".cursor" / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {
        ANVYC_MCP_KEY: {"command": ANVYC_MCP_COMMAND, "args": list(ANVYC_MCP_ARGS)},
        "context7": {"command": "npx", "args": ["context7"]},
    }}))

    result = CliRunner().invoke(
        app, ["mcp", "uninstall", "--ide", "cursor", "--apply", "--yes"]
    )
    assert result.exit_code == 0
    data = json.loads(cfg.read_text())
    assert ANVYC_MCP_KEY not in data["mcpServers"]
    assert "context7" in data["mcpServers"]


def test_install_invalid_ide(fake_home: Path) -> None:
    result = CliRunner().invoke(app, ["mcp", "install", "--ide", "vscode"])
    assert result.exit_code == 2


def test_install_auto_no_ide_detected(fake_home: Path) -> None:
    """`--ide auto` 가 detect 결과 0 일 때 noop + 안내."""
    result = CliRunner().invoke(app, ["mcp", "install"])
    assert result.exit_code == 0
    assert "no IDE detected" in result.stdout


def test_install_with_claude_config_dir_env(fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`CLAUDE_CONFIG_DIR` env var 가 set 일 때 그 경로에 작성."""
    custom = fake_home / ".claude-edward"
    custom.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(custom))

    result = CliRunner().invoke(
        app, ["mcp", "install", "--ide", "claude", "--apply", "--yes"]
    )
    assert result.exit_code == 0
    assert (custom / "mcp.json").is_file()
    # default ~/.claude/mcp.json 은 미작성
    assert not (fake_home / ".claude" / "mcp.json").is_file()
