"""tests/unit/test_agents_cursor.py — CP-10 v5 (Cursor adapter 실 구현).

ADR `role-based-ruleset/docs/adr/v5-cp10-cursor-observability.md` 의 decision
(a) impl 검증. cursorDiskKV.composerData enumerate + session metadata 추출
의 정확성 + edge case (빈 SQLite / 손상 / cursorDiskKV 미존재 / invalid JSON).

읽기 안전성:
- read-only SQLite URI (mode=ro) 사용
- conversation 본문 미반환 — count + tools_used 만 검증

격리:
- monkeypatch.setattr(cursor_module, "DEFAULT_CURSOR_USER_DIR", tmp_path)
  로 실머신 ~/Library/Application Support/Cursor 의 누설 방지.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from anvyc.agents import cursor as cursor_mod
from anvyc.agents.cursor import (
    CursorAdapter,
    discover_cursor_sqlites,
    parse_cursor_session,
)


def make_fake_cursor_sqlite(
    path: Path,
    composers: int = 2,
    bubbles_per_composer: int = 3,
    tools_per_composer: tuple[str, ...] = ("search", "read", "edit"),
    include_cursor_disk_kv: bool = True,
) -> Path:
    """합성 Cursor state.vscdb 생성.

    실 Cursor 의 schema 와 호환되는 최소 형태 — ItemTable + cursorDiskKV +
    composerData/bubbleId 키. include_cursor_disk_kv=False 시 legacy 버전
    시뮬레이션 (cursorDiskKV 부재).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
        if include_cursor_disk_kv:
            conn.execute(
                "CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
            )
            for i in range(composers):
                composer_id = f"comp{i}"
                bubble_ids = [f"bub{i}_{j}" for j in range(bubbles_per_composer)]
                composer_data = {
                    "composerId": composer_id,
                    "bubbleIds": bubble_ids,
                    "conversation": [
                        {"role": "user", "type": "text"},
                        *[
                            {"role": "assistant", "toolName": t, "type": "tool_use"}
                            for t in tools_per_composer
                        ],
                    ],
                }
                conn.execute(
                    "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
                    (
                        f"composerData:{composer_id}",
                        json.dumps(composer_data).encode("utf-8"),
                    ),
                )
                for bub_id in bubble_ids:
                    bubble = {"text": f"bubble {bub_id}", "role": "user"}
                    conn.execute(
                        "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
                        (
                            f"bubbleId:{composer_id}:{bub_id}",
                            json.dumps(bubble).encode("utf-8"),
                        ),
                    )
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture
def fake_cursor_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """DEFAULT_CURSOR_USER_DIR 을 tmp_path 로 patch + globalStorage / workspaceStorage 생성."""
    monkeypatch.setattr(cursor_mod, "DEFAULT_CURSOR_USER_DIR", tmp_path)
    monkeypatch.delenv("ANVYC_CURSOR_USER_DIR", raising=False)
    (tmp_path / "globalStorage").mkdir()
    (tmp_path / "workspaceStorage").mkdir()
    return tmp_path


# --------------- discover_cursor_sqlites ---------------


def test_discover_empty_dir_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cursor_mod, "DEFAULT_CURSOR_USER_DIR", tmp_path / "nonexistent")
    assert discover_cursor_sqlites() == []


def test_discover_dir_missing_storage_subdirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """user_dir 은 존재하지만 globalStorage / workspaceStorage 미존재."""
    monkeypatch.setattr(cursor_mod, "DEFAULT_CURSOR_USER_DIR", tmp_path)
    assert discover_cursor_sqlites() == []


def test_discover_global_only(fake_cursor_dir: Path) -> None:
    make_fake_cursor_sqlite(fake_cursor_dir / "globalStorage" / "state.vscdb")
    found = discover_cursor_sqlites()
    assert len(found) == 1
    assert found[0].name == "state.vscdb"
    assert found[0].parent.name == "globalStorage"


def test_discover_workspace_only(fake_cursor_dir: Path) -> None:
    ws = fake_cursor_dir / "workspaceStorage"
    make_fake_cursor_sqlite(ws / "abc123" / "state.vscdb")
    make_fake_cursor_sqlite(ws / "def456" / "state.vscdb")
    found = discover_cursor_sqlites()
    assert len(found) == 2
    assert {p.parent.name for p in found} == {"abc123", "def456"}


def test_discover_global_plus_workspace_sorted(fake_cursor_dir: Path) -> None:
    make_fake_cursor_sqlite(fake_cursor_dir / "globalStorage" / "state.vscdb")
    ws = fake_cursor_dir / "workspaceStorage"
    make_fake_cursor_sqlite(ws / "abc" / "state.vscdb")
    make_fake_cursor_sqlite(ws / "zzz" / "state.vscdb")
    found = discover_cursor_sqlites()
    # globalStorage 가 먼저, 그 다음 workspaceStorage 의 alphabetical
    assert [p.parent.name for p in found] == ["globalStorage", "abc", "zzz"]


def test_discover_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ANVYC_CURSOR_USER_DIR env override 가 DEFAULT 보다 우선."""
    custom = tmp_path / "custom-cursor"
    (custom / "globalStorage").mkdir(parents=True)
    make_fake_cursor_sqlite(custom / "globalStorage" / "state.vscdb")

    monkeypatch.setattr(cursor_mod, "DEFAULT_CURSOR_USER_DIR", tmp_path / "ignored")
    monkeypatch.setenv("ANVYC_CURSOR_USER_DIR", str(custom))

    found = discover_cursor_sqlites()
    assert len(found) == 1
    assert found[0].parent.parent == custom


# --------------- parse_cursor_session ---------------


def test_parse_normal_returns_session(tmp_path: Path) -> None:
    db = make_fake_cursor_sqlite(
        tmp_path / "globalStorage" / "state.vscdb",
        composers=2,
        bubbles_per_composer=3,
        tools_per_composer=("search", "read", "search"),
    )
    s = parse_cursor_session(db)
    assert s is not None
    assert s.session_id == "cursor:globalStorage"
    assert s.cwd == "cursor-workspace://globalStorage"
    # 2 composer × 3 bubble = 6 events
    assert s.event_count == 6
    # 각 composer 의 conversation 에 search + read + search = 3 tool, × 2 composer = 6
    assert s.tool_call_count == 6
    assert s.tools_used == {"search": 4, "read": 2}


def test_parse_empty_cursor_disk_kv_returns_none(tmp_path: Path) -> None:
    db = make_fake_cursor_sqlite(tmp_path / "empty" / "state.vscdb", composers=0)
    assert parse_cursor_session(db) is None


def test_parse_missing_cursor_disk_kv_returns_none(tmp_path: Path) -> None:
    """legacy Cursor 버전 시뮬레이션 (cursorDiskKV 테이블 부재)."""
    db = make_fake_cursor_sqlite(
        tmp_path / "legacy" / "state.vscdb",
        include_cursor_disk_kv=False,
    )
    assert parse_cursor_session(db) is None


def test_parse_corrupted_sqlite_returns_none(tmp_path: Path) -> None:
    db = tmp_path / "corrupt.vscdb"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"not a sqlite file")
    assert parse_cursor_session(db) is None


def test_parse_invalid_json_value_skipped_gracefully(tmp_path: Path) -> None:
    """composerData 의 value 가 invalid JSON — 그 composer 만 tools_used 0,
    composer_count 는 여전히 증가 (조용히 skip)."""
    db = tmp_path / "ws" / "state.vscdb"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE ItemTable (key TEXT, value BLOB)")
    conn.execute(
        "CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
    )
    # 정상 + invalid 섞임
    conn.execute(
        "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
        ("composerData:ok", json.dumps({"bubbleIds": ["b1", "b2"]}).encode()),
    )
    conn.execute(
        "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
        ("composerData:bad", b"<<< not json >>>"),
    )
    conn.commit()
    conn.close()

    s = parse_cursor_session(db)
    assert s is not None
    # 2 composer, ok 의 2 bubble 만 카운트 (bad 는 0)
    assert s.event_count == 2
    assert s.tool_call_count == 0


def test_parse_no_bubble_ids_uses_composer_count(tmp_path: Path) -> None:
    """bubbleIds 부재 시 event_count 가 composer_count 로 폴백."""
    db = tmp_path / "noib" / "state.vscdb"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            (f"composerData:c{i}", json.dumps({"foo": "bar"}).encode()),
        )
    conn.commit()
    conn.close()

    s = parse_cursor_session(db)
    assert s is not None
    assert s.event_count == 3  # composer_count fallback


def test_parse_missing_file_returns_none(tmp_path: Path) -> None:
    assert parse_cursor_session(tmp_path / "nonexistent.vscdb") is None


# --------------- CursorAdapter ---------------


def test_adapter_supports_hooks_false() -> None:
    adapter = CursorAdapter()
    assert adapter.supports_hooks() is False
    assert adapter.hook_wire_targets() == []


def test_adapter_discover_and_parse_e2e(fake_cursor_dir: Path) -> None:
    """adapter 의 discover + parse 통합 — registry 없이 직접."""
    make_fake_cursor_sqlite(fake_cursor_dir / "globalStorage" / "state.vscdb", composers=1)
    make_fake_cursor_sqlite(fake_cursor_dir / "workspaceStorage" / "ws1" / "state.vscdb", composers=2)

    adapter = CursorAdapter()
    paths = list(adapter.discover_session_files())
    assert len(paths) == 2

    sessions = [adapter.parse_session(p) for p in paths]
    sessions_filtered = [s for s in sessions if s is not None]
    assert len(sessions_filtered) == 2
    # global = 1 composer × 3 bubble (default), ws1 = 2 composer × 3 bubble
    assert sessions_filtered[0].event_count == 3  # global
    assert sessions_filtered[1].event_count == 6  # ws1


def test_adapter_registered_in_registry() -> None:
    """register_agent() 가 side-effect import 로 호출됐는지 확인."""
    from anvyc.agents import AGENT_REGISTRY

    assert "cursor" in AGENT_REGISTRY
    # impl 적용 후에도 isinstance(CursorAdapter) 확인 가능
    assert isinstance(AGENT_REGISTRY["cursor"], CursorAdapter)
