"""실체 조회 캐시 — TTL 만료·원본 mtime 변화 시 재조회."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core import identity_cache


@pytest.fixture()
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "cache"
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(d))
    return d


def test_probe_called_once_then_cached(cache_dir: Path) -> None:
    calls: list[int] = []

    def probe() -> str | None:
        calls.append(1)
        return "16bitdo"

    assert identity_cache.probe_cached("gh:16bitdo", None, probe) == "16bitdo"
    assert identity_cache.probe_cached("gh:16bitdo", None, probe) == "16bitdo"
    assert len(calls) == 1


def test_ttl_expiry_triggers_reprobe(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def probe() -> str | None:
        calls.append(1)
        return f"acct{len(calls)}"

    now = [1_000_000.0]
    monkeypatch.setattr(identity_cache.time, "time", lambda: now[0])

    assert identity_cache.probe_cached("k", None, probe, ttl=100) == "acct1"
    now[0] += 101
    assert identity_cache.probe_cached("k", None, probe, ttl=100) == "acct2"
    assert len(calls) == 2


def test_source_mtime_change_invalidates(cache_dir: Path, tmp_path: Path) -> None:
    src = tmp_path / "profile"
    src.mkdir()
    calls: list[int] = []

    def probe() -> str | None:
        calls.append(1)
        return f"acct{len(calls)}"

    assert identity_cache.probe_cached("k", src, probe) == "acct1"
    assert identity_cache.probe_cached("k", src, probe) == "acct1"
    import os
    os.utime(src, (2_000_000, 2_000_000))
    assert identity_cache.probe_cached("k", src, probe) == "acct2"


def test_none_result_is_not_cached(cache_dir: Path) -> None:
    """조회 실패는 캐시하지 않는다 — 일시적 장애를 8시간 고정하지 않기 위해."""
    calls: list[int] = []

    def probe() -> str | None:
        calls.append(1)
        return None

    assert identity_cache.probe_cached("k", None, probe) is None
    assert identity_cache.probe_cached("k", None, probe) is None
    assert len(calls) == 2


def test_corrupt_cache_file_is_tolerated(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "identity.json").write_text("{ not json", encoding="utf-8")
    assert identity_cache.probe_cached("k", None, lambda: "ok") == "ok"
