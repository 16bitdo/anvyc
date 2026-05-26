"""tests/unit/test_workctx.py — CP-12 PR-12E workctx 회귀.

anvyc/core/workctx 의 schema v1 호환성 + explicit row TTL 관리 + statusline
resolver 와 priority 일관성 검증.
"""
from __future__ import annotations

import os
import stat

from anvyc.core import workctx


def _read_lines(path) -> list[str]:
    with path.open("r", encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f if ln.strip()]


def test_parse_and_serialize_roundtrip():
    line = "1779780000\texplicit\t/Users/x/dev/y\tttl=1800;expires_at=1779781800"
    row = workctx.WorkCwdRow.parse(line)
    assert row is not None
    assert row.ts == 1779780000
    assert row.kind == "explicit"
    assert row.path == "/Users/x/dev/y"
    assert row.serialize() == line
    assert row.explicit_expires_at == 1779781800
    assert row.explicit_ttl == 1800


def test_parse_rejects_malformed():
    assert workctx.WorkCwdRow.parse("garbage") is None
    assert workctx.WorkCwdRow.parse("a\tb\tc") is None  # 3 fields
    assert workctx.WorkCwdRow.parse("nan\texplicit\t/x\tttl=1") is None


def test_is_expired_for_explicit():
    row = workctx.WorkCwdRow(
        ts=1000,
        kind="explicit",
        path="/x",
        source_detail="ttl=100;expires_at=1100",
    )
    assert not row.is_expired(now=1050)
    assert row.is_expired(now=1100)
    assert row.is_expired(now=1200)


def test_activity_row_never_expired():
    row = workctx.WorkCwdRow(ts=1000, kind="cwd_changed", path="/x", source_detail="old=/y")
    assert not row.is_expired(now=10_000_000)  # statusline 60s TTL 은 reader-side


def test_switch_writes_explicit_row(tmp_path):
    cache = tmp_path / "test-cache"
    row = workctx.switch(cache, "/Users/x/dev/y", ttl_sec=1800, now=1000)
    assert row.path == "/Users/x/dev/y"
    assert row.explicit_expires_at == 2800
    assert cache.exists()
    lines = _read_lines(cache)
    assert len(lines) == 1
    assert lines[0] == "1000\texplicit\t/Users/x/dev/y\tttl=1800;expires_at=2800"
    # 권한 600
    mode = stat.S_IMODE(cache.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_switch_preserves_activity_rows(tmp_path):
    cache = tmp_path / "cache"
    cache.parent.mkdir(parents=True, exist_ok=True)
    # 기존 activity row
    cache.write_text(
        "500\tcwd_changed\t/x\told=/y\n"
        "600\tfile_op\t/x\ttool=Read\n",
        encoding="utf-8",
    )
    workctx.switch(cache, "/Users/a/b", ttl_sec=1800, now=1000)
    lines = _read_lines(cache)
    assert len(lines) == 3
    assert "cwd_changed" in lines[0]
    assert "file_op" in lines[1]
    assert "explicit\t/Users/a/b" in lines[2]


def test_switch_cleans_expired_explicit(tmp_path):
    cache = tmp_path / "cache"
    # 기존 만료 explicit + activity row
    cache.write_text(
        "500\texplicit\t/old/path\tttl=100;expires_at=600\n"
        "700\tcwd_changed\t/y\told=/x\n",
        encoding="utf-8",
    )
    workctx.switch(cache, "/new/path", ttl_sec=1800, now=1000)
    lines = _read_lines(cache)
    # 만료 explicit 제거됨, activity 보존, 새 explicit 추가
    assert len(lines) == 2
    assert "cwd_changed" in lines[0]
    assert "explicit\t/new/path" in lines[1]


def test_clear_removes_explicit_only(tmp_path):
    cache = tmp_path / "cache"
    cache.write_text(
        "500\tcwd_changed\t/x\told=/y\n"
        "600\texplicit\t/a\tttl=1800;expires_at=2400\n"
        "700\tfile_op\t/x\ttool=Read\n"
        "800\texplicit\t/b\tttl=1800;expires_at=2600\n",
        encoding="utf-8",
    )
    removed = workctx.clear(cache)
    assert removed == 2
    lines = _read_lines(cache)
    assert len(lines) == 2
    assert all("explicit" not in ln for ln in lines)


def test_clear_on_missing_cache(tmp_path):
    cache = tmp_path / "missing"
    removed = workctx.clear(cache)
    assert removed == 0
    # write_cache 가 빈 파일로 생성
    assert cache.exists()


def test_status_priority_explicit_over_activity(tmp_path):
    cache = tmp_path / "cache"
    # 더 최근 activity + 더 오래된 fresh explicit → explicit 우선
    cache.write_text(
        "500\texplicit\t/explicit-path\tttl=1800;expires_at=2300\n"
        "1000\tcwd_changed\t/activity-path\told=/x\n",
        encoding="utf-8",
    )
    state = workctx.status(cache, now=1010)
    assert state.effective_kind == "explicit"
    assert state.effective.path == "/explicit-path"
    assert state.effective_remaining_sec == 2300 - 1010


def test_status_expired_explicit_falls_back_to_activity(tmp_path):
    cache = tmp_path / "cache"
    cache.write_text(
        "100\texplicit\t/old\tttl=100;expires_at=200\n"
        "500\tcwd_changed\t/recent\told=/x\n",
        encoding="utf-8",
    )
    state = workctx.status(cache, now=510)
    assert state.effective_kind == "cwd_changed"
    assert state.effective.path == "/recent"
    assert state.effective_age_sec == 10
    assert state.effective_stale is False


def test_status_stale_activity(tmp_path):
    cache = tmp_path / "cache"
    cache.write_text("100\tcwd_changed\t/x\told=/y\n", encoding="utf-8")
    state = workctx.status(cache, now=200)  # age=100s > 60
    assert state.effective_kind == "cwd_changed"
    assert state.effective_age_sec == 100
    assert state.effective_stale is True


def test_status_empty_cache(tmp_path):
    cache = tmp_path / "missing"
    state = workctx.status(cache)
    assert state.effective is None
    assert state.rows == []


def test_write_cache_fifo_truncation(tmp_path):
    cache = tmp_path / "cache"
    rows = [
        workctx.WorkCwdRow(ts=i, kind="cwd_changed", path=f"/p{i}", source_detail=f"i={i}")
        for i in range(25)
    ]
    workctx.write_cache(cache, rows)
    lines = _read_lines(cache)
    assert len(lines) == workctx.MAX_ROWS  # 20
    # 가장 최근 20개만 (i=5..24)
    assert lines[0].startswith("5\t")
    assert lines[-1].startswith("24\t")


def test_default_cache_path():
    home = os.path.expanduser("~")
    assert str(workctx.default_cache_path("claude")) == f"{home}/.claude/.work-cwd-cache"
    assert str(workctx.default_cache_path("claude-edward")) == f"{home}/.claude-edward/.work-cwd-cache"


def test_resolve_cache_path_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("WORK_CWD_CACHE", str(tmp_path / "custom"))
    assert workctx.resolve_cache_path(profile="claude-edward") == tmp_path / "custom"
    monkeypatch.delenv("WORK_CWD_CACHE")
    home = os.path.expanduser("~")
    assert str(workctx.resolve_cache_path(profile="claude-edward")) == f"{home}/.claude-edward/.work-cwd-cache"


def test_cleanup_expired_explicit_filters_correctly():
    rows = [
        workctx.WorkCwdRow(ts=100, kind="cwd_changed", path="/x", source_detail="old=/y"),
        workctx.WorkCwdRow(ts=200, kind="explicit", path="/a", source_detail="ttl=100;expires_at=300"),  # expired
        workctx.WorkCwdRow(ts=400, kind="explicit", path="/b", source_detail="ttl=1000;expires_at=1400"),  # fresh
        workctx.WorkCwdRow(ts=500, kind="file_op", path="/x", source_detail="tool=Read"),
    ]
    cleaned = workctx.cleanup_expired_explicit(rows, now=600)
    assert len(cleaned) == 3
    # 만료 explicit 만 제거
    paths = [r.path for r in cleaned]
    assert "/a" not in paths
    assert "/b" in paths
    assert "/x" in paths
