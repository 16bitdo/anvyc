"""MCP server 자동 등록 — Claude Code / Cursor 의 mcp.json 작성/제거.

`anvyc mcp install|uninstall|status` CLI 의 backend. 직접 JSON 편집 부담을 해소하고
`CLAUDE_CONFIG_DIR` 라우팅을 인지한다. atomic write 패턴은
`core/sync.py:_atomic_write_manifest` 미러 (tempfile + os.replace).

핵심 원칙:
- 기존 `mcpServers` 의 **다른 server entry 항상 보존** (read-modify-write merge).
- 기존 anvyc entry 가 다른 command (사용자 wrapper) 면 `.bak` 자동 생성 후 표준값
  으로 overwrite — plan 단계에서 `current_state="present_diff"` 로 명시.
- JSON parse 실패는 fail-fast (write 안 함).
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ANVYC_MCP_KEY = "anvyc"
ANVYC_MCP_COMMAND = "anvyc"
ANVYC_MCP_ARGS = ["serve", "--mcp"]

IDE_CLAUDE = "claude"
IDE_CURSOR = "cursor"
KNOWN_IDES = (IDE_CLAUDE, IDE_CURSOR)

SCOPE_USER = "user"
SCOPE_PROJECT = "project"


# ---------- path resolution ------------------------------------------------


def claude_mcp_config_path(
    home: Path | None = None,
    *,
    claude_config_dir: str | None = None,
    scope: str = SCOPE_USER,
    cwd: Path | None = None,
) -> Path:
    """Claude Code 의 `mcp.json` 경로 결정.

    scope=user:
      - `claude_config_dir` (=`$CLAUDE_CONFIG_DIR`) 가 set 이면 `<dir>/mcp.json`
      - 미set 이면 `<home>/.claude/mcp.json`
    scope=project: `<cwd>/.mcp.json` (Claude Code 의 project-local convention)

    `CLAUDE_CONFIG_DIR` 인지는 `core/project_info.py:_derive_claude_account` 의
    경로 해석과 정합 — leading `$HOME` / `~` 확장.
    """
    if scope == SCOPE_PROJECT:
        base = (cwd or Path.cwd()).resolve()
        return base / ".mcp.json"

    home = home or Path.home()
    if claude_config_dir:
        from anvyc.core.project_info import expand_envrc_path

        return expand_envrc_path(claude_config_dir).resolve() / "mcp.json"
    return home / ".claude" / "mcp.json"


def cursor_mcp_config_path(
    home: Path | None = None,
    *,
    scope: str = SCOPE_USER,
    cwd: Path | None = None,
) -> Path:
    """Cursor 의 `mcp.json` 경로 결정.

    scope=user:    `<home>/.cursor/mcp.json`
    scope=project: `<cwd>/.cursor/mcp.json`
    """
    if scope == SCOPE_PROJECT:
        base = (cwd or Path.cwd()).resolve()
        return base / ".cursor" / "mcp.json"

    home = home or Path.home()
    return home / ".cursor" / "mcp.json"


def detect_installed_ides(
    home: Path | None = None,
    *,
    claude_config_dir: str | None = None,
) -> list[str]:
    """존재 IDE 추출 — claude / cursor 디렉터리 존재 확인.

    `CLAUDE_CONFIG_DIR` 가 set 이면 그 경로의 존재로 판정 (default `~/.claude` 미사용).
    `~/.cursor` 디렉터리 존재로 cursor 판정.
    """
    home = home or Path.home()
    detected: list[str] = []

    if claude_config_dir:
        from anvyc.core.project_info import expand_envrc_path

        claude_dir = expand_envrc_path(claude_config_dir)
    else:
        claude_dir = home / ".claude"
    if claude_dir.is_dir():
        detected.append(IDE_CLAUDE)

    if (home / ".cursor").is_dir():
        detected.append(IDE_CURSOR)

    return detected


def resolve_ides(ide_opt: str, *, home: Path | None = None, claude_config_dir: str | None = None) -> list[str]:
    """`--ide` 옵션 값 → IDE 목록.

    `auto` → detect_installed_ides 결과. `both` → 명시 양쪽.
    `claude` / `cursor` → 단일.
    """
    if ide_opt == "auto":
        return detect_installed_ides(home=home, claude_config_dir=claude_config_dir)
    if ide_opt == "both":
        return list(KNOWN_IDES)
    if ide_opt in KNOWN_IDES:
        return [ide_opt]
    raise ValueError(f"unknown --ide: {ide_opt} (expected: claude | cursor | both | auto)")


def _config_path_for(
    ide: str,
    *,
    scope: str,
    home: Path | None,
    claude_config_dir: str | None,
    cwd: Path | None,
) -> Path:
    if ide == IDE_CLAUDE:
        return claude_mcp_config_path(home, claude_config_dir=claude_config_dir, scope=scope, cwd=cwd)
    if ide == IDE_CURSOR:
        return cursor_mcp_config_path(home, scope=scope, cwd=cwd)
    raise ValueError(f"unknown ide: {ide}")


# ---------- mcp.json read / parse ------------------------------------------


def _read_mcp_json(path: Path) -> dict[str, Any] | None:
    """mcp.json 읽기. 미존재 → None. parse 실패 → raise JSONDecodeError."""
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        data: Any = json.load(fh)
    return data if isinstance(data, dict) else None


def _make_anvyc_entry() -> dict[str, Any]:
    return {"command": ANVYC_MCP_COMMAND, "args": list(ANVYC_MCP_ARGS)}


def _existing_other_servers(data: dict[str, Any] | None) -> list[str]:
    """mcpServers 에서 anvyc 제외한 server 이름 목록."""
    if not data:
        return []
    servers = data.get("mcpServers") or {}
    if not isinstance(servers, dict):
        return []
    return sorted(k for k in servers if k != ANVYC_MCP_KEY)


def _anvyc_entry_in(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not data:
        return None
    servers = data.get("mcpServers") or {}
    entry = servers.get(ANVYC_MCP_KEY) if isinstance(servers, dict) else None
    return entry if isinstance(entry, dict) else None


def _entries_equal(a: dict[str, Any] | None, b: dict[str, Any]) -> bool:
    if a is None:
        return False
    return a.get("command") == b.get("command") and list(a.get("args") or []) == list(b.get("args") or [])


# ---------- plan / apply / uninstall ---------------------------------------


@dataclass(frozen=True)
class McpInstallPlan:
    target_path: Path
    ide: str
    scope: str
    current_state: str  # "missing" | "absent_entry" | "present_same" | "present_diff"
    will_write_new_file: bool
    existing_servers: list[str]
    backup_path: Path | None  # `.bak` (current_state == "present_diff" 일 때만 set)


@dataclass(frozen=True)
class McpInstallResult:
    plan: McpInstallPlan
    written: bool
    backup_written: bool


def plan_install(
    ides: list[str],
    *,
    scope: str = SCOPE_USER,
    home: Path | None = None,
    claude_config_dir: str | None = None,
    cwd: Path | None = None,
) -> list[McpInstallPlan]:
    """install 의 dry-run plan — 파일 변경 없음."""
    plans: list[McpInstallPlan] = []
    target_entry = _make_anvyc_entry()

    for ide in ides:
        path = _config_path_for(ide, scope=scope, home=home, claude_config_dir=claude_config_dir, cwd=cwd)
        data = _read_mcp_json(path)
        existing = _existing_other_servers(data)
        anvyc_existing = _anvyc_entry_in(data)

        if data is None:
            state = "missing"
            backup = None
        elif anvyc_existing is None:
            state = "absent_entry"
            backup = None
        elif _entries_equal(anvyc_existing, target_entry):
            state = "present_same"
            backup = None
        else:
            state = "present_diff"
            backup = path.with_name(path.name + ".bak")

        plans.append(
            McpInstallPlan(
                target_path=path,
                ide=ide,
                scope=scope,
                current_state=state,
                will_write_new_file=(data is None),
                existing_servers=existing,
                backup_path=backup,
            )
        )

    return plans


def apply_install(plans: list[McpInstallPlan]) -> list[McpInstallResult]:
    """plan_install 결과를 실 적용 — atomic write."""
    target_entry = _make_anvyc_entry()
    results: list[McpInstallResult] = []

    for plan in plans:
        if plan.current_state == "present_same":
            results.append(McpInstallResult(plan=plan, written=False, backup_written=False))
            continue

        path = plan.target_path
        path.parent.mkdir(parents=True, exist_ok=True)

        existing_data = _read_mcp_json(path) if path.is_file() else None

        backup_written = False
        if plan.current_state == "present_diff" and plan.backup_path is not None:
            with path.open("rb") as src, plan.backup_path.open("wb") as dst:
                dst.write(src.read())
            backup_written = True

        if existing_data is None:
            new_data: dict[str, Any] = {"mcpServers": {ANVYC_MCP_KEY: target_entry}}
        else:
            new_data = dict(existing_data)
            servers = dict(new_data.get("mcpServers") or {})
            servers[ANVYC_MCP_KEY] = target_entry
            new_data["mcpServers"] = servers

        _atomic_write_json(path, new_data)
        results.append(McpInstallResult(plan=plan, written=True, backup_written=backup_written))

    return results


@dataclass(frozen=True)
class McpUninstallPlan:
    target_path: Path
    ide: str
    scope: str
    current_state: str  # "missing" | "absent_entry" | "present"
    remaining_servers: list[str]
    will_delete_file: bool  # anvyc 가 유일 entry 였다면 빈 mcpServers 가 남음 — 파일은 보존


def plan_uninstall(
    ides: list[str],
    *,
    scope: str = SCOPE_USER,
    home: Path | None = None,
    claude_config_dir: str | None = None,
    cwd: Path | None = None,
) -> list[McpUninstallPlan]:
    plans: list[McpUninstallPlan] = []
    for ide in ides:
        path = _config_path_for(ide, scope=scope, home=home, claude_config_dir=claude_config_dir, cwd=cwd)
        data = _read_mcp_json(path)
        existing = _existing_other_servers(data)
        if data is None:
            state = "missing"
        elif _anvyc_entry_in(data) is None:
            state = "absent_entry"
        else:
            state = "present"
        plans.append(
            McpUninstallPlan(
                target_path=path,
                ide=ide,
                scope=scope,
                current_state=state,
                remaining_servers=existing,
                will_delete_file=False,
            )
        )
    return plans


@dataclass(frozen=True)
class McpUninstallResult:
    plan: McpUninstallPlan
    removed: bool


def apply_uninstall(plans: list[McpUninstallPlan]) -> list[McpUninstallResult]:
    results: list[McpUninstallResult] = []
    for plan in plans:
        if plan.current_state != "present":
            results.append(McpUninstallResult(plan=plan, removed=False))
            continue

        path = plan.target_path
        data = _read_mcp_json(path) or {}
        new_data = dict(data)
        servers = dict(new_data.get("mcpServers") or {})
        servers.pop(ANVYC_MCP_KEY, None)
        new_data["mcpServers"] = servers
        _atomic_write_json(path, new_data)
        results.append(McpUninstallResult(plan=plan, removed=True))
    return results


# ---------- status ----------------------------------------------------------


@dataclass(frozen=True)
class McpStatus:
    ide: str
    scope: str
    path: Path
    exists: bool
    has_anvyc: bool
    anvyc_command: str | None
    anvyc_args: list[str] | None
    other_servers: list[str] = field(default_factory=list)


def collect_status(
    *,
    home: Path | None = None,
    claude_config_dir: str | None = None,
    cwd: Path | None = None,
    scope: str = SCOPE_USER,
) -> list[McpStatus]:
    """양쪽 IDE 의 mcp.json 등록 상태 read-only 조회."""
    rows: list[McpStatus] = []
    for ide in KNOWN_IDES:
        path = _config_path_for(ide, scope=scope, home=home, claude_config_dir=claude_config_dir, cwd=cwd)
        data = _read_mcp_json(path) if path.is_file() else None
        anvyc_entry = _anvyc_entry_in(data)
        rows.append(
            McpStatus(
                ide=ide,
                scope=scope,
                path=path,
                exists=path.is_file(),
                has_anvyc=anvyc_entry is not None,
                anvyc_command=anvyc_entry.get("command") if anvyc_entry else None,
                anvyc_args=list(anvyc_entry.get("args") or []) if anvyc_entry else None,
                other_servers=_existing_other_servers(data),
            )
        )
    return rows


# ---------- atomic write (sync.py:_atomic_write_manifest 패턴 미러) ----------


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """JSON atomic write — tempfile.mkstemp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
