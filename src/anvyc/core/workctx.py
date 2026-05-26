"""anvyc/core/workctx.py — Work-cwd context (CP-12 PR-12E).

`.work-cwd-cache` schema v1 의 `explicit` kind row 관리. 사용자 명시 컨텍스트
전환 채널 — Bash `cd` 가 불가능한 시나리오 (1Password sandbox / sub-shell
격리 / 명시 override 의도) 에서 statusline / agent 가 인식할 work 경로 강제.

페어 PR:
- rbr#83 (PR-12A): CwdChanged event hook — cache writer (kind=cwd_changed)
- rbr#84 (PR-12D): PostToolUse hook — cache writer (kind=file_op)
- cci#17 (PR-12C): statusline resolver — cache reader (explicit 우선 처리)

캐시 schema v1 (TSV, append-only, max 20 row, chmod 600):
    <ts_unix>\t<kind>\t<git_toplevel_abs>\t<source_detail>
    kind ∈ { cwd_changed, file_op, explicit }
    본 모듈: kind=explicit, source_detail="ttl=<sec>;expires_at=<ts>"

TTL 정책 (소프트 expiry):
- switch 호출 시 expires_at 을 source_detail 에 인코딩.
- statusline reader (PR-12C) 는 explicit row 가 있으면 항상 valid 로 간주
  (TTL 미체크, 빠른 경로 유지).
- anvyc workctx 호출 시 (switch / clear / show) 만료된 explicit row lazy
  cleanup. 호출 없이 expire 된 row 는 FIFO rotation (20 row 한계) 에 의해
  최종 drop.
- 결과: 사용자가 1800s 내 anvyc 미호출 + activity 가 적으면 만료 row 가
  잠시 잔존 — 다음 호출 시 정리. 트레이드오프: 단순한 hot path / 정확한
  TTL 강제 사이 균형.
"""
from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

CACHE_SCHEMA_VERSION = 1
MAX_ROWS = 20
DEFAULT_TTL_SEC = 1800  # 30 분
EXPLICIT_KIND = "explicit"
ACTIVITY_KINDS = ("cwd_changed", "file_op")


@dataclass
class WorkCwdRow:
    """TSV row of .work-cwd-cache schema v1."""

    ts: int
    kind: str
    path: str
    source_detail: str

    @classmethod
    def parse(cls, line: str) -> WorkCwdRow | None:
        """Parse a TSV line. Returns None on malformed input."""
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 4:
            return None
        try:
            ts = int(parts[0])
        except ValueError:
            return None
        return cls(ts=ts, kind=parts[1], path=parts[2], source_detail=parts[3])

    def serialize(self) -> str:
        return f"{self.ts}\t{self.kind}\t{self.path}\t{self.source_detail}"

    @property
    def explicit_expires_at(self) -> int | None:
        """For explicit rows, parse expires_at from source_detail. None otherwise."""
        if self.kind != EXPLICIT_KIND:
            return None
        for tok in self.source_detail.split(";"):
            tok = tok.strip()
            if tok.startswith("expires_at="):
                try:
                    return int(tok.split("=", 1)[1])
                except ValueError:
                    return None
        return None

    @property
    def explicit_ttl(self) -> int | None:
        """For explicit rows, parse ttl from source_detail. None otherwise."""
        if self.kind != EXPLICIT_KIND:
            return None
        for tok in self.source_detail.split(";"):
            tok = tok.strip()
            if tok.startswith("ttl="):
                try:
                    return int(tok.split("=", 1)[1])
                except ValueError:
                    return None
        return None

    def is_expired(self, now: int | None = None) -> bool:
        """True if explicit row past expires_at. Activity rows never 'expire' here."""
        exp = self.explicit_expires_at
        if exp is None:
            return False
        return exp <= (now if now is not None else int(time.time()))


@dataclass
class WorkCwdState:
    """Summary of current cache + effective work-cwd."""

    cache_path: Path
    rows: list[WorkCwdRow] = field(default_factory=list)
    effective: WorkCwdRow | None = None
    effective_kind: str | None = None  # explicit | cwd_changed | file_op | None
    effective_remaining_sec: int | None = None  # explicit TTL 잔여
    effective_age_sec: int | None = None  # activity row 나이
    effective_stale: bool = False  # activity > 60s


def default_cache_path(profile: str = "claude") -> Path:
    """Return per-profile cache path.

    Conventions:
    - profile == 'claude'    → ~/.claude/.work-cwd-cache
    - profile == 'claude-X'  → ~/.claude-X/.work-cwd-cache
    """
    home = Path.home()
    if profile == "claude":
        return home / ".claude" / ".work-cwd-cache"
    return home / f".{profile}" / ".work-cwd-cache"


def resolve_cache_path(profile: str | None = None) -> Path:
    """Cache path resolution: $WORK_CWD_CACHE > profile-derived > ~/.claude/."""
    env = os.environ.get("WORK_CWD_CACHE")
    if env:
        return Path(env).expanduser()
    if profile:
        return default_cache_path(profile)
    return default_cache_path("claude")


def read_cache(cache_path: Path) -> list[WorkCwdRow]:
    """Read cache file, parse rows. Returns empty list on missing/unreadable."""
    if not cache_path.exists():
        return []
    rows: list[WorkCwdRow] = []
    try:
        with cache_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                row = WorkCwdRow.parse(line)
                if row is not None:
                    rows.append(row)
    except OSError:
        return []
    return rows


def write_cache(cache_path: Path, rows: Iterable[WorkCwdRow]) -> None:
    """Atomic write: tempfile + os.replace + chmod 600. FIFO truncate to MAX_ROWS."""
    rows_list = list(rows)[-MAX_ROWS:]
    cache_dir = cache_path.parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".work-cwd-cache.", dir=str(cache_dir))
    import contextlib

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for row in rows_list:
                f.write(row.serialize() + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, cache_path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def cleanup_expired_explicit(rows: list[WorkCwdRow], now: int | None = None) -> list[WorkCwdRow]:
    """Drop expired `explicit` rows. Activity rows untouched (statusline 60s TTL is reader-side)."""
    n = now if now is not None else int(time.time())
    return [r for r in rows if not (r.kind == EXPLICIT_KIND and r.is_expired(n))]


def switch(
    cache_path: Path,
    path: str,
    ttl_sec: int = DEFAULT_TTL_SEC,
    now: int | None = None,
) -> WorkCwdRow:
    """Write explicit override row. Cleans expired explicit rows first.

    Args:
        cache_path: target cache file.
        path: absolute path to override to (caller should pre-resolve).
        ttl_sec: explicit TTL in seconds.
        now: override current time (for tests).

    Returns the newly written WorkCwdRow.
    """
    ts = now if now is not None else int(time.time())
    expires_at = ts + ttl_sec
    row = WorkCwdRow(
        ts=ts,
        kind=EXPLICIT_KIND,
        path=path,
        source_detail=f"ttl={ttl_sec};expires_at={expires_at}",
    )
    existing = cleanup_expired_explicit(read_cache(cache_path), now=ts)
    existing.append(row)
    write_cache(cache_path, existing)
    return row


def clear(cache_path: Path) -> int:
    """Remove all explicit rows. Activity rows preserved. Returns removed count."""
    existing = read_cache(cache_path)
    kept = [r for r in existing if r.kind != EXPLICIT_KIND]
    removed = len(existing) - len(kept)
    write_cache(cache_path, kept)
    return removed


def status(cache_path: Path, now: int | None = None) -> WorkCwdState:
    """Compute effective work-cwd from cache.

    Priority (matches statusline resolver, cci#17):
    1. Latest non-expired explicit row.
    2. Latest activity row (cwd_changed | file_op), stale flag if age > 60s.
    3. None.
    """
    n = now if now is not None else int(time.time())
    rows = read_cache(cache_path)
    state = WorkCwdState(cache_path=cache_path, rows=rows)
    if not rows:
        return state

    latest_explicit: WorkCwdRow | None = None
    latest_activity: WorkCwdRow | None = None
    for r in rows:
        if r.kind == EXPLICIT_KIND and not r.is_expired(n):
            latest_explicit = r
        elif r.kind in ACTIVITY_KINDS:
            latest_activity = r

    if latest_explicit is not None:
        state.effective = latest_explicit
        state.effective_kind = EXPLICIT_KIND
        exp = latest_explicit.explicit_expires_at or 0
        state.effective_remaining_sec = max(0, exp - n)
    elif latest_activity is not None:
        state.effective = latest_activity
        state.effective_kind = latest_activity.kind
        age = n - latest_activity.ts
        state.effective_age_sec = age
        state.effective_stale = age > 60
    return state
