"""실체 조회 결과 캐시 — 훅이 매 명령마다 네트워크를 타지 않게 한다.

배선된 PreToolUse 훅은 Bash 명령마다 `anvyc project doctor --json` 을 호출한다.
실체 조회가 매번 네트워크를 타면 명령당 수백 ms 가 붙는다. 토큰 오염은 며칠 단위로
지속되는 상태이지 초 단위로 변하지 않으므로, TTL + 원본 mtime 무효화로 충분하다.

Atomic write (tempfile + os.replace) — 동시에 여러 명령이 서로 다른 key 로 캐시에
접근할 때 last-write-wins 에서 일부 항목이 손실되는 것을 방지한다 (CP-4 snapshot 패턴 미러).

source 는 무효화 트리거(config hosts.yml 등 실제 파일). 파일 mtime 은 in-place 수정·
tmp+os.replace 양쪽에서 갱신되므로 소스 변경을 확실히 감지할 수 있다. (디렉터리 mtime 은
파일 in-place 수정에 갱신되지 않으므로 파일이어야 함.)

캐시에는 **public identifier(계정명·이메일·계정 ID)만** 담는다. 토큰·키는 담지 않는다.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
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
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError:
        return  # 캐시 실패는 기능 실패가 아니다


def _mtime(source: Path | None) -> float | None:
    if source is None:
        return None
    try:
        return source.stat().st_mtime
    except OSError:
        return None


def probe_cached(
    key: str,
    source: Path | None,
    probe: Callable[[], str | None],
    ttl: int = _DEFAULT_TTL,
) -> str | None:
    """`key` 의 실체를 캐시에서 읽거나, 만료·mtime 변화 시 `probe()` 로 갱신.

    - `source` 는 무효화 트리거(config 파일 등). None 이면 TTL 만 본다.
    - `probe()` 가 None 을 반환하면 **캐시하지 않는다** — 일시적 장애를 고정하지 않기 위해.
    """
    data = _load()
    entry = data.get(key)
    now = time.time()
    src_mtime = _mtime(source)

    if isinstance(entry, dict):
        fresh = (now - float(entry.get("at", 0))) < ttl
        same_source = entry.get("source_mtime") == src_mtime
        if fresh and same_source and entry.get("value"):
            return str(entry["value"])

    value = probe()
    if value is None:
        return None
    data[key] = {"value": value, "at": now, "source_mtime": src_mtime}
    _save(data)
    return value
