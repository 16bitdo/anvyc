"""Unit tests for anvyc.core.mcp_setup (PR A — mcp install/uninstall/status)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anvyc.core.mcp_setup import (
    ANVYC_MCP_ARGS,
    ANVYC_MCP_COMMAND,
    ANVYC_MCP_KEY,
    IDE_CLAUDE,
    IDE_CURSOR,
    apply_install,
    apply_uninstall,
    claude_mcp_config_path,
    collect_status,
    cursor_mcp_config_path,
    detect_installed_ides,
    plan_install,
    plan_uninstall,
    resolve_ides,
)

# ---------- path resolution ------------------------------------------------


def test_claude_user_default(tmp_path: Path) -> None:
    p = claude_mcp_config_path(home=tmp_path)
    assert p == tmp_path / ".claude" / "mcp.json"


def test_claude_with_config_dir_env(tmp_path: Path) -> None:
    custom = tmp_path / ".claude-edward"
    custom.mkdir()
    p = claude_mcp_config_path(home=tmp_path, claude_config_dir=str(custom))
    assert p == custom.resolve() / "mcp.json"


def test_claude_project_scope(tmp_path: Path) -> None:
    p = claude_mcp_config_path(home=tmp_path, scope="project", cwd=tmp_path / "repo")
    assert p == (tmp_path / "repo").resolve() / ".mcp.json"


def test_cursor_user(tmp_path: Path) -> None:
    p = cursor_mcp_config_path(home=tmp_path)
    assert p == tmp_path / ".cursor" / "mcp.json"


def test_cursor_project(tmp_path: Path) -> None:
    p = cursor_mcp_config_path(home=tmp_path, scope="project", cwd=tmp_path / "repo")
    assert p == (tmp_path / "repo").resolve() / ".cursor" / "mcp.json"


# ---------- detect / resolve ----------------------------------------------


def test_detect_neither(tmp_path: Path) -> None:
    assert detect_installed_ides(home=tmp_path) == []


def test_detect_claude_only(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    assert detect_installed_ides(home=tmp_path) == [IDE_CLAUDE]


def test_detect_both(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".cursor").mkdir()
    assert detect_installed_ides(home=tmp_path) == [IDE_CLAUDE, IDE_CURSOR]


def test_detect_via_claude_config_dir(tmp_path: Path) -> None:
    custom = tmp_path / ".claude-edward"
    custom.mkdir()
    assert detect_installed_ides(home=tmp_path, claude_config_dir=str(custom)) == [IDE_CLAUDE]
    # `~/.claude` 디렉터리는 없어도 CLAUDE_CONFIG_DIR 가 있으면 인지


def test_resolve_ides_auto(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir()
    assert resolve_ides("auto", home=tmp_path) == [IDE_CURSOR]


def test_resolve_ides_both(tmp_path: Path) -> None:
    assert resolve_ides("both", home=tmp_path) == [IDE_CLAUDE, IDE_CURSOR]


def test_resolve_ides_single(tmp_path: Path) -> None:
    assert resolve_ides("cursor", home=tmp_path) == [IDE_CURSOR]


def test_resolve_ides_invalid(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown --ide"):
        resolve_ides("vscode", home=tmp_path)


# ---------- plan_install ---------------------------------------------------


def test_plan_install_missing_file(tmp_path: Path) -> None:
    plans = plan_install([IDE_CURSOR], home=tmp_path)
    assert len(plans) == 1
    assert plans[0].current_state == "missing"
    assert plans[0].will_write_new_file is True
    assert plans[0].existing_servers == []
    assert plans[0].backup_path is None


def test_plan_install_absent_entry(tmp_path: Path) -> None:
    """기존 mcp.json 에 다른 server 만 있을 때."""
    (tmp_path / ".cursor").mkdir()
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"context7": {"command": "npx"}}}))
    plans = plan_install([IDE_CURSOR], home=tmp_path)
    assert plans[0].current_state == "absent_entry"
    assert plans[0].will_write_new_file is False
    assert plans[0].existing_servers == ["context7"]


def test_plan_install_present_same(tmp_path: Path) -> None:
    """이미 표준 anvyc entry 가 있을 때."""
    (tmp_path / ".cursor").mkdir()
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {ANVYC_MCP_KEY: {"command": ANVYC_MCP_COMMAND, "args": list(ANVYC_MCP_ARGS)}}}))
    plans = plan_install([IDE_CURSOR], home=tmp_path)
    assert plans[0].current_state == "present_same"
    assert plans[0].backup_path is None


def test_plan_install_present_diff(tmp_path: Path) -> None:
    """기존 anvyc entry 가 다른 command (사용자 wrapper) 일 때."""
    (tmp_path / ".cursor").mkdir()
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {ANVYC_MCP_KEY: {"command": "/usr/local/bin/anvyc-wrapper"}}}))
    plans = plan_install([IDE_CURSOR], home=tmp_path)
    assert plans[0].current_state == "present_diff"
    assert plans[0].backup_path == cfg.with_name(cfg.name + ".bak")


# ---------- apply_install --------------------------------------------------


def test_apply_install_missing_creates_file(tmp_path: Path) -> None:
    plans = plan_install([IDE_CURSOR], home=tmp_path)
    results = apply_install(plans)
    assert results[0].written is True

    cfg = tmp_path / ".cursor" / "mcp.json"
    assert cfg.is_file()
    data = json.loads(cfg.read_text())
    assert data["mcpServers"][ANVYC_MCP_KEY] == {
        "command": ANVYC_MCP_COMMAND,
        "args": list(ANVYC_MCP_ARGS),
    }


def test_apply_install_preserves_existing_servers(tmp_path: Path) -> None:
    """다른 server entry 가 있을 때 read-modify-write merge 정상."""
    (tmp_path / ".cursor").mkdir()
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"context7": {"command": "npx", "args": ["context7"]}}}))

    plans = plan_install([IDE_CURSOR], home=tmp_path)
    apply_install(plans)

    data = json.loads(cfg.read_text())
    assert set(data["mcpServers"].keys()) == {"context7", ANVYC_MCP_KEY}
    assert data["mcpServers"]["context7"] == {"command": "npx", "args": ["context7"]}
    assert data["mcpServers"][ANVYC_MCP_KEY] == {
        "command": ANVYC_MCP_COMMAND,
        "args": list(ANVYC_MCP_ARGS),
    }


def test_apply_install_present_same_is_noop(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir()
    cfg = tmp_path / ".cursor" / "mcp.json"
    initial = {"mcpServers": {ANVYC_MCP_KEY: {"command": ANVYC_MCP_COMMAND, "args": list(ANVYC_MCP_ARGS)}}}
    cfg.write_text(json.dumps(initial))
    mtime_before = cfg.stat().st_mtime

    plans = plan_install([IDE_CURSOR], home=tmp_path)
    results = apply_install(plans)
    assert results[0].written is False
    # 동일이면 atomic write 미발생 (mtime 보존)
    assert cfg.stat().st_mtime == mtime_before


def test_apply_install_present_diff_creates_bak(tmp_path: Path) -> None:
    """기존 anvyc entry 가 다른 command — .bak 자동 생성 후 표준값 overwrite."""
    (tmp_path / ".cursor").mkdir()
    cfg = tmp_path / ".cursor" / "mcp.json"
    initial = {"mcpServers": {ANVYC_MCP_KEY: {"command": "/usr/local/bin/anvyc-wrapper"}}}
    cfg.write_text(json.dumps(initial))

    plans = plan_install([IDE_CURSOR], home=tmp_path)
    results = apply_install(plans)
    assert results[0].written is True
    assert results[0].backup_written is True

    bak = cfg.with_name(cfg.name + ".bak")
    assert bak.is_file()
    assert json.loads(bak.read_text()) == initial

    data = json.loads(cfg.read_text())
    assert data["mcpServers"][ANVYC_MCP_KEY] == {
        "command": ANVYC_MCP_COMMAND,
        "args": list(ANVYC_MCP_ARGS),
    }


def test_apply_install_creates_parent_dir(tmp_path: Path) -> None:
    """`~/.cursor` 디렉터리도 없을 때 mkdir 후 생성."""
    plans = plan_install([IDE_CURSOR], home=tmp_path)
    assert plans[0].will_write_new_file is True
    apply_install(plans)
    assert (tmp_path / ".cursor" / "mcp.json").is_file()


def test_apply_install_invalid_json_raises(tmp_path: Path) -> None:
    """parse 실패 시 fail-fast (write 안 함)."""
    (tmp_path / ".cursor").mkdir()
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.write_text("{ not json")

    with pytest.raises(json.JSONDecodeError):
        plan_install([IDE_CURSOR], home=tmp_path)
    # plan 단계에서 raise — file 무변경
    assert cfg.read_text() == "{ not json"


# ---------- uninstall ------------------------------------------------------


def test_plan_uninstall_missing(tmp_path: Path) -> None:
    plans = plan_uninstall([IDE_CURSOR], home=tmp_path)
    assert plans[0].current_state == "missing"


def test_plan_uninstall_absent_entry(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"context7": {"command": "npx"}}})
    )
    plans = plan_uninstall([IDE_CURSOR], home=tmp_path)
    assert plans[0].current_state == "absent_entry"


def test_plan_uninstall_present(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {
            ANVYC_MCP_KEY: {"command": ANVYC_MCP_COMMAND, "args": list(ANVYC_MCP_ARGS)},
            "context7": {"command": "npx"},
        }})
    )
    plans = plan_uninstall([IDE_CURSOR], home=tmp_path)
    assert plans[0].current_state == "present"
    assert plans[0].remaining_servers == ["context7"]


def test_apply_uninstall_preserves_others(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir()
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {
        ANVYC_MCP_KEY: {"command": ANVYC_MCP_COMMAND, "args": list(ANVYC_MCP_ARGS)},
        "context7": {"command": "npx", "args": ["context7"]},
    }}))

    plans = plan_uninstall([IDE_CURSOR], home=tmp_path)
    results = apply_uninstall(plans)
    assert results[0].removed is True

    data = json.loads(cfg.read_text())
    assert ANVYC_MCP_KEY not in data["mcpServers"]
    assert data["mcpServers"]["context7"] == {"command": "npx", "args": ["context7"]}


# ---------- status ---------------------------------------------------------


def test_collect_status_both_missing(tmp_path: Path) -> None:
    rows = collect_status(home=tmp_path)
    assert len(rows) == 2
    assert all(not r.exists for r in rows)
    assert all(not r.has_anvyc for r in rows)


def test_collect_status_one_registered(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {
            ANVYC_MCP_KEY: {"command": ANVYC_MCP_COMMAND, "args": list(ANVYC_MCP_ARGS)},
            "notion": {"command": "npx"},
        }})
    )
    rows = collect_status(home=tmp_path)
    by_ide = {r.ide: r for r in rows}
    assert by_ide[IDE_CURSOR].has_anvyc is True
    assert by_ide[IDE_CURSOR].anvyc_command == ANVYC_MCP_COMMAND
    assert by_ide[IDE_CURSOR].other_servers == ["notion"]
    assert by_ide[IDE_CLAUDE].has_anvyc is False


def test_collect_status_via_claude_config_dir(tmp_path: Path) -> None:
    custom = tmp_path / ".claude-edward"
    custom.mkdir()
    (custom / "mcp.json").write_text(
        json.dumps({"mcpServers": {ANVYC_MCP_KEY: {"command": ANVYC_MCP_COMMAND, "args": list(ANVYC_MCP_ARGS)}}})
    )

    rows = collect_status(home=tmp_path, claude_config_dir=str(custom))
    by_ide = {r.ide: r for r in rows}
    assert by_ide[IDE_CLAUDE].path == custom.resolve() / "mcp.json"
    assert by_ide[IDE_CLAUDE].has_anvyc is True
