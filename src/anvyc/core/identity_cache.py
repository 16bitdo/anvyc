"""실체 조회 결과 캐시 — 훅이 매 명령마다 네트워크를 타지 않게 한다.

배선된 PreToolUse 훅은 Bash 명령마다 `anvyc project doctor --json` 을 호출한다.
실체 조회가 매번 네트워크를 타면 명령당 수백 ms 가 붙는다. 토큰 오염은 며칠 단위로
지속되는 상태이지 초 단위로 변하지 않으므로, TTL + 원본 mtime 무효화로 충분하다.

Atomic write (tempfile + os.replace) — 동시 쓰기 중에도 파일이 손상되지 않으므로
_load() 가 반쪽짜리 JSON 을 읽지 않는다 (CP-4 snapshot 패턴 미러). 서로 다른 key
간 lost update(A 의 조회 후 B 가 쓰기 → A 가 쓰기하면 B 값이 소실)는 락이 없어
방지되지 않으나, 다음 조회에서 자동 재probe 되므로 허용 가능하다.

source 는 무효화 트리거(config hosts.yml 등 실제 파일). 파일 mtime 은 in-place 수정·
tmp+os.replace 양쪽에서 갱신되므로 소스 변경을 확실히 감지할 수 있다. (디렉터리 mtime 은
파일 in-place 수정에 갱신되지 않으므로 파일이어야 함.)

source 는 단일 Path 뿐 아니라 여러 Path 도 받는다 — OR 시맨틱으로 무효화한다(그중
하나라도 mtime 이 바뀌면 전체 무효화). 자격이 여러 파일에 걸쳐 공유되는 경우(예:
gh CLI 프로필들이 라벨은 GH_CONFIG_DIR 로 분리해도 토큰은 OS 키체인을 공유 —
2026-08-12 실측: 프로필 A 에서 재인증하면 A 자신의 hosts.yml 은 안 바뀐 프로필 B 의
API 응답까지 함께 바뀐다) 단일 파일 감시로는 그 변화를 놓친다.

캐시에는 **public identifier(계정명·이메일·계정 ID)만** 담는다. 토큰·키는 담지 않는다.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path

_DEFAULT_TTL = 8 * 3600


def cache_path() -> Path:
    base = os.environ.get("ANVYC_CACHE_DIR")
    root = Path(base) if base else Path.home() / ".config" / "anvyc" / "cache"
    return root / "identity.json"


def _load() -> dict[str, dict]:
    p = cache_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, dict]) -> None:
    """Atomic write using tempfile + os.replace. 쓰기 실패는 조용히 넘긴다."""
    p = cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=".identity-", suffix=".json.tmp", dir=p.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
            p.chmod(0o600)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
    except Exception:
        return  # 캐시 실패는 기능 실패가 아니다


def _mtime(source: Path | None) -> float | None:
    if source is None:
        return None
    try:
        return source.stat().st_mtime
    except OSError:
        return None


def _normalize_sources(source: Path | Iterable[Path] | None) -> tuple[Path, ...]:
    """단일 `Path`·`Path` 의 iterable·`None` 을 하나의 tuple 로 정규화.

    기존 호출부(단일 `Path` 또는 `None`)를 그대로 받아들이면서, 여러 파일을
    한꺼번에 무효화 트리거로 쓰려는 호출부도 지원한다.
    """
    if source is None:
        return ()
    if isinstance(source, Path):
        return (source,)
    return tuple(source)


def _signature(sources: tuple[Path, ...]) -> list[list[object]]:
    """여러 source 파일의 mtime 을 정렬된 하나의 서명으로 묶는다.

    경로 문자열 기준 정렬 — 호출자가 다른 순서로 넘겨도 같은 서명이 나온다.
    JSON 저장 후 다시 읽은 값과 형태가 같아야 비교가 성립하므로(JSON 에는 tuple
    이 없다) list of list 로 구성한다.
    """
    return [[str(p), _mtime(p)] for p in sorted(sources, key=str)]


def probe_cached(
    key: str,
    source: Path | Iterable[Path] | None,
    probe: Callable[[], str | None],
    ttl: int = _DEFAULT_TTL,
) -> str | None:
    """`key` 의 실체를 캐시에서 읽거나, 만료·source 변화 시 `probe()` 로 갱신.

    - `source` 는 무효화 트리거 — 단일 `Path`, 여러 `Path` 의 iterable, 또는 `None`.
      여러 개를 주면 OR 시맨틱: 그중 **하나라도** mtime 이 바뀌면 전체를 무효화한다.
      `None`/빈 컬렉션이면 TTL 만 본다.
    - `probe()` 가 None 을 반환하면 **캐시하지 않는다** — 일시적 장애를 고정하지 않기 위해.
    - 캐시 스키마가 이전(`source_mtime` 단일 값)과 달라졌다 — 옛 항목은 키 자체가
      달라 그냥 미스 처리되어 재조회된다. 별도 마이그레이션은 하지 않는다(최악의
      결과가 "한 번 더 조회"뿐이라 안전한 방향).
    """
    sources = _normalize_sources(source)
    data = _load()
    entry = data.get(key)
    now = time.time()
    sig = _signature(sources)

    if isinstance(entry, dict):
        fresh = (now - float(entry.get("at", 0))) < ttl
        same_source = entry.get("source_sig") == sig
        if fresh and same_source and entry.get("value"):
            return str(entry["value"])

    value = probe()
    if value is None:
        return None
    data[key] = {"value": value, "at": now, "source_sig": sig}
    _save(data)
    return value
