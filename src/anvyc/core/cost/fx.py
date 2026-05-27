"""FX rate fetch (CP-13 PR-13B2).

USD → KRW 환율을 open.er-api.com 에서 fetch (무인증 / 무 rate limit).
ADR v1.2 §2.1 의 FX 출처 결정 정합. cache TTL=1d / stale 7d WARNING /
14d 시 `FxStaleError` raise — DESIGN §38.5 retention 정책 미러.

dep 정책: stdlib `urllib.request` 만 사용 — anvyc core dep (typer / rich /
pathspec / pyyaml) 외 추가 없음 (ADR R11 mitigation).
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from anvyc.core.cost.cache import CACHE_ROOT

OPEN_ER_API_URL = "https://open.er-api.com/v6/latest/USD"
FX_CACHE_DIR = CACHE_ROOT / "fx"
FX_SOURCE = "open.er-api.com"
STALE_WARN_DAYS = 7
STALE_FATAL_DAYS = 14
STALE_SEARCH_MAX_DAYS = 60  # boundary detection — fatal 초과 cache 도 발견 후 FxStaleError raise
FETCH_TIMEOUT_SEC = 10.0


@dataclass(frozen=True)
class FxRate:
    """USD → target 환율 + 메타.

    `basis_string()` = `CostReport.fx_rate_basis` 필드 형식
    (`'open.er-api.com:2026-05-27'`).
    """

    base: str
    target: str
    rate: float
    fetched_at: datetime
    cache_age_days: int = 0
    is_stale: bool = False

    def basis_string(self) -> str:
        return f"{FX_SOURCE}:{self.fetched_at.date().isoformat()}"


class FxStaleError(RuntimeError):
    """cache 가 `STALE_FATAL_DAYS` 이상 + remote fetch 실패.

    statusline 의 `~` prefix visual cue trigger. caller 가 catch 시 USD only
    표시로 graceful fallback.
    """


class FxFetchError(RuntimeError):
    """remote fetch + cache 부재 — 최초 사용 시 network 없으면 발생."""


def _fx_cache_path(day: date, root: Path | None = None) -> Path:
    base = root or FX_CACHE_DIR
    return base / f"{day.isoformat()}.json"


def _write_fx_cache(
    payload: dict[str, Any], day: date, root: Path | None = None
) -> Path:
    """atomic write (tempfile + os.replace, CP-4/6 패턴 미러)."""
    path = _fx_cache_path(day, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".fx-", suffix=".json.tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def _read_fx_cache(day: date, root: Path | None = None) -> dict[str, Any] | None:
    path = _fx_cache_path(day, root)
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        return None


def _iter_recent_fx_cache(
    *,
    today: date,
    max_age_days: int,
    root: Path | None = None,
) -> tuple[dict[str, Any], date] | None:
    """today 부터 max_age_days 까지 역순 search — 가장 신선한 cache 반환."""
    for offset in range(max_age_days + 1):
        day = today - timedelta(days=offset)
        data = _read_fx_cache(day, root)
        if data is not None:
            return data, day
    return None


def _fetch_remote(timeout: float = FETCH_TIMEOUT_SEC) -> dict[str, Any]:
    """open.er-api.com 호출. 실패 시 raise `FxFetchError`."""
    req = urllib.request.Request(  # noqa: S310 — public read-only API
        OPEN_ER_API_URL,
        headers={"User-Agent": "anvyc-cost/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as e:
        raise FxFetchError(f"FX fetch failed: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise FxFetchError(f"FX response not JSON: {e}") from e
    if not isinstance(data, dict) or data.get("result") != "success":
        raise FxFetchError(
            f"FX response invalid: {data!r}"
            if isinstance(data, dict)
            else "FX response not dict"
        )
    return data


def get_usd_to_krw_rate(
    *,
    today: date | None = None,
    cache_root: Path | None = None,
    force_refresh: bool = False,
) -> FxRate:
    """USD → KRW 환율 (cache 우선).

    동작 순서:
      1. force_refresh=False 일 때 — 오늘 cache 가 있으면 그 즉시 반환
         (TTL=1d).
      2. remote fetch 시도. 성공 시 cache 저장 + 반환.
      3. remote 실패 시 — STALE_FATAL_DAYS 이내 cache search:
         - cache 있고 age <= STALE_WARN_DAYS → `is_stale=False` 반환
         - cache 있고 STALE_WARN_DAYS < age <= STALE_FATAL_DAYS → `is_stale=True`
         - 그 외 → raise FxStaleError (or FxFetchError if cache 부재)
    """
    today_actual = today or datetime.now(UTC).date()

    # 1) Today's cache (TTL=1d) — force_refresh 가 아니면 우선
    if not force_refresh:
        cached = _read_fx_cache(today_actual, cache_root)
        if cached is not None:
            return _build_fx_rate(cached, today_actual, today_actual)

    # 2) Remote fetch
    try:
        data = _fetch_remote()
        _write_fx_cache(data, today_actual, cache_root)
        return _build_fx_rate(data, today_actual, today_actual)
    except FxFetchError as fetch_err:
        # 3) Cache fallback — STALE_SEARCH_MAX_DAYS 까지 search 후 age 검사로
        # STALE_FATAL_DAYS 초과 여부 판정 (boundary case 검출).
        recent = _iter_recent_fx_cache(
            today=today_actual,
            max_age_days=STALE_SEARCH_MAX_DAYS,
            root=cache_root,
        )
        if recent is None:
            # Cache 부재 + fetch 실패 — 최초 사용 시 network 없음
            raise FxFetchError(
                "FX cache absent and remote fetch failed; cannot compute KRW"
            ) from fetch_err

        cached_data, cached_day = recent
        age_days = (today_actual - cached_day).days
        if age_days > STALE_FATAL_DAYS:
            raise FxStaleError(
                f"FX cache {age_days}d old (> {STALE_FATAL_DAYS}d fatal) "
                f"and remote fetch failed"
            ) from fetch_err
        is_stale = age_days > STALE_WARN_DAYS
        return _build_fx_rate(
            cached_data,
            today_actual,
            cached_day,
            cache_age_days=age_days,
            is_stale=is_stale,
        )


def _build_fx_rate(
    data: dict[str, Any],
    today: date,
    cached_day: date,
    cache_age_days: int = 0,
    is_stale: bool = False,
) -> FxRate:
    rates = data.get("rates")
    if not isinstance(rates, dict):
        raise FxFetchError(f"FX response 'rates' missing or invalid: {data!r}")
    krw_raw = rates.get("KRW")
    if not isinstance(krw_raw, int | float):
        raise FxFetchError(
            f"FX response missing 'KRW' rate or invalid type: {krw_raw!r}"
        )
    krw_rate = float(krw_raw)
    return FxRate(
        base="USD",
        target="KRW",
        rate=krw_rate,
        fetched_at=datetime.combine(cached_day, datetime.min.time(), tzinfo=UTC),
        cache_age_days=cache_age_days,
        is_stale=is_stale,
    )


def try_get_usd_to_krw_rate(
    *,
    today: date | None = None,
    cache_root: Path | None = None,
) -> FxRate | None:
    """`FxFetchError` / `FxStaleError` graceful — `None` 반환.

    summary 등에서 KRW 노출 시 사용 — 실패 시 USD only 로 자연 fallback.
    """
    try:
        return get_usd_to_krw_rate(today=today, cache_root=cache_root)
    except (FxFetchError, FxStaleError):
        return None


__all__ = [
    "FX_CACHE_DIR",
    "FX_SOURCE",
    "FxFetchError",
    "FxRate",
    "FxStaleError",
    "OPEN_ER_API_URL",
    "STALE_FATAL_DAYS",
    "STALE_WARN_DAYS",
    "get_usd_to_krw_rate",
    "try_get_usd_to_krw_rate",
]
