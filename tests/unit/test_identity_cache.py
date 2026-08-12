"""실체 조회 캐시 — TTL 만료·원본 mtime 변화 시 재조회."""
from __future__ import annotations

import json
import os
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


def test_none_result_is_not_cached(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """조회 실패는 캐시하지 않는다 — 일시적 장애를 8시간 고정하지 않기 위해."""
    calls: list[int] = []
    save_calls: list[int] = []

    def probe() -> str | None:
        calls.append(1)
        return None

    original_save = identity_cache._save

    def tracked_save(data: dict) -> None:
        save_calls.append(1)
        return original_save(data)

    monkeypatch.setattr(identity_cache, "_save", tracked_save)

    assert identity_cache.probe_cached("k", None, probe) is None
    assert identity_cache.probe_cached("k", None, probe) is None
    assert len(calls) == 2
    # 핵심: None 값은 저장되지 않는다
    assert len(save_calls) == 0


def test_corrupt_cache_file_is_tolerated(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "identity.json").write_text("{ not json", encoding="utf-8")
    assert identity_cache.probe_cached("k", None, lambda: "ok") == "ok"


def test_save_failure_is_tolerated(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """캐시 쓰기 실패는 기능 실패가 아니다 — probe 결과는 여전히 반환된다."""
    def probe() -> str | None:
        return "result"

    # os.replace()를 실패하도록 monkeypatch → _save 내부의 try/except가 catch
    original_replace = os.replace

    def failing_replace(src: str, dst: str) -> None:
        raise OSError("권한 부족")

    monkeypatch.setattr("os.replace", failing_replace)

    # 첫 번째 호출: 쓰기 실패하지만 결과 반환
    result1 = identity_cache.probe_cached("k", None, probe)
    assert result1 == "result"

    # 두 번째 호출: 캐시가 없으므로(쓰기 실패) 재호출
    result2 = identity_cache.probe_cached("k", None, probe)
    assert result2 == "result"


def test_non_oserror_exception_is_tolerated(cache_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """json.dump TypeError 같은 다른 예외도 cleanup되고 조용히 넘어간다."""
    def probe() -> str | None:
        return "result"

    # json.dump()를 TypeError 발생하도록 monkeypatch
    # (직렬화 불가능한 객체를 넘겨야 하지만, 테스트에선 직접 json.dump를 mock)
    original_dump = json.dump

    def failing_dump(obj, fp, **kwargs):
        raise TypeError("Object of type object is not JSON serializable")

    monkeypatch.setattr("json.dump", failing_dump)

    # 호출: TypeError가 아니라 조용히 None(또는 정상 동작)
    # 실제로는 _save() 내에서 cleanup되고 조용히 넘어감
    result = identity_cache.probe_cached("k", None, probe)
    assert result == "result"  # 성공적으로 값 반환 (TypeError 미전파)

    # tempfile이 cleanup되었는지 확인 (temp 파일이 남아있지 않음)
    cache_dir_path = Path(cache_dir)
    temp_files = list(cache_dir_path.glob("*.json.tmp")) if cache_dir_path.exists() else []
    assert len(temp_files) == 0, "tempfile이 cleanup되지 않았음"

    json.dump = original_dump
