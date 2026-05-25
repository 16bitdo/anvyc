"""Cursor IDE agent adapter (CP-10 v5 — impl).

ADR `role-based-ruleset/docs/adr/v5-cp10-cursor-observability.md` 의 decision
(a) 따라 실 구현. Cursor 가 VS Code fork 라 conversation 본문이 다음 SQLite
에 저장됨:

  ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb
  ~/Library/Application Support/Cursor/User/workspaceStorage/<md5>/state.vscdb

각 SQLite 의 `cursorDiskKV` 테이블 (Cursor 전용 key/value) 의 key 패턴:
  composerData:<composerId>                       — session metadata
  bubbleId:<composerId>:<bubbleId>                — 개별 메시지

본 어댑터는 **session metadata only** 반환 (count + tools_used). conversation
본문은 anvyc 외부로 노출 X — ADR §3.2 R4 정책.

read-only safety:
  - sqlite3 의 read-only URI (`mode=ro`) + immutable=0 (active write 허용)
  - busy timeout 5s
  - graceful skip 시점: 손상 SQLite / cursorDiskKV 미존재 (legacy 버전) /
    빈 composerData
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from anvyc.agents.base import UNIFIED_SCHEMA_VERSION, register_agent
from anvyc.core.activity import Session

# 모듈-level 상수 — 테스트는 monkeypatch.setattr 로 격리.
DEFAULT_CURSOR_USER_DIR = Path.home() / "Library" / "Application Support" / "Cursor" / "User"
GLOBAL_STORAGE_REL = Path("globalStorage") / "state.vscdb"
WORKSPACE_STORAGE_REL = Path("workspaceStorage")
COMPOSER_KEY_PREFIX = "composerData:"


def _cursor_user_dir() -> Path:
    """ANVYC_CURSOR_USER_DIR env override 우선, 없으면 DEFAULT.

    test 격리 시 monkeypatch.setenv 또는 setattr(module, "DEFAULT_CURSOR_USER_DIR")
    중 하나로 가능. env override 는 비-macOS 환경 (Linux 향후) 대응.
    """
    override = os.environ.get("ANVYC_CURSOR_USER_DIR")
    if override:
        return Path(override).expanduser()
    return DEFAULT_CURSOR_USER_DIR


def discover_cursor_sqlites(user_dir: Path | None = None) -> list[Path]:
    """globalStorage + workspaceStorage 의 모든 state.vscdb 경로 (정렬).

    user_dir 미지정 시 `_cursor_user_dir()` 사용. 결정론적 순회를 위해
    sorted.
    """
    base = user_dir or _cursor_user_dir()
    found: list[Path] = []
    if not base.is_dir():
        return found
    global_db = base / GLOBAL_STORAGE_REL
    if global_db.is_file():
        found.append(global_db)
    workspace_dir = base / WORKSPACE_STORAGE_REL
    if workspace_dir.is_dir():
        for entry in sorted(workspace_dir.iterdir()):
            if not entry.is_dir():
                continue
            db = entry / "state.vscdb"
            if db.is_file():
                found.append(db)
    return found


def _extract_tool_calls_from_composer(value: bytes) -> tuple[int, Counter[str]]:
    """composerData blob 에서 tool 호출 카운트 + 이름 추출.

    Cursor 의 schema 가 비공식 — 다양한 형식 가능. best-effort 로 알려진
    key 들을 탐색 (community reverse engineering 자료 기반):

    - data["conversation"][*] 의 each item 에서 "toolName" 또는 "type"
      추출
    - data["bubbleIds"] 는 bubble count 의 source (event_count 계산용)

    parse 실패는 silent skip (0, empty Counter).
    """
    try:
        data = json.loads(value.decode("utf-8") if isinstance(value, bytes) else value)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return 0, Counter()
    if not isinstance(data, dict):
        return 0, Counter()

    bubble_ids = data.get("bubbleIds")
    bubble_count = len(bubble_ids) if isinstance(bubble_ids, list) else 0

    tools_used: Counter[str] = Counter()
    conversation = data.get("conversation")
    if isinstance(conversation, list):
        for item in conversation:
            if not isinstance(item, dict):
                continue
            # 알려진 키 우선순위: toolName > tool_name > name
            tool_name = item.get("toolName") or item.get("tool_name")
            if isinstance(tool_name, str) and tool_name:
                tools_used[tool_name] += 1
    return bubble_count, tools_used


def parse_cursor_session(path: Path) -> Session | None:
    """SQLite 1 파일 (workspace 또는 global) 의 composerData 집계 → 1 Session.

    빈 cursorDiskKV / 빈 composerData / 손상 SQLite / cursorDiskKV 미존재
    (legacy 버전) → None 반환 (silent skip — activity 의 union 통계에서 제외).

    conversation 본문 미반환 — count + tools_used 만.
    """
    # read-only URI — active write lock 허용 (immutable=0). busy timeout 5s.
    uri = f"file:{path}?mode=ro&immutable=0"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error:
        return None

    try:
        cur = conn.cursor()
        # legacy Cursor 버전 (cursorDiskKV 미존재) → graceful skip
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'"
        )
        if cur.fetchone() is None:
            return None

        cur.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE ?",
            (COMPOSER_KEY_PREFIX + "%",),
        )
        rows = cur.fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    if not rows:
        return None

    composer_count = 0
    total_bubbles = 0
    tools_used: Counter[str] = Counter()
    for _key, value in rows:
        composer_count += 1
        bubbles, tools = _extract_tool_calls_from_composer(value)
        total_bubbles += bubbles
        tools_used.update(tools)

    # session_id = SQLite 의 parent dir 이름 (workspace md5 hash 또는 "globalStorage").
    # cwd 는 path 매핑 부재 — 1차 impl 은 hint 만. workspace ↔ path 매핑은 v6+.
    session_id = f"cursor:{path.parent.name}"
    cwd_hint = f"cursor-workspace://{path.parent.name}"

    return Session(
        session_id=session_id,
        source_path=path,
        cwd=cwd_hint,
        git_branch=None,
        started_at=None,
        ended_at=None,
        event_count=total_bubbles or composer_count,
        tool_call_count=sum(tools_used.values()),
        tools_used=tools_used,
    )


class CursorAdapter:
    """Cursor IDE conversation observability — `state.vscdb` 의 cursorDiskKV
    의 composerData 집계.

    1 SQLite = 1 Session (workspace 또는 global). conversation 본문은 anvyc
    외부로 노출 X — ADR v5-CP-10 §3.2 R4 정책.
    """

    name = "cursor"
    unified_schema_version = UNIFIED_SCHEMA_VERSION

    def discover_session_files(self) -> Iterator[Path]:
        yield from discover_cursor_sqlites()

    def parse_session(self, path: Path) -> Session | None:
        return parse_cursor_session(path)

    def supports_hooks(self) -> bool:
        # Cursor 의 PreToolUse hook 인터페이스 부재 — _schema.yaml 일관.
        # alternative 차단 채널은 v6+ (CP-12 후보).
        return False

    def hook_wire_targets(self) -> list[Path]:
        return []


register_agent(CursorAdapter())
