"""Unit tests for anvyc.core.cost.fx (CP-13 PR-13B2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from anvyc.core.cost.fx import (
    FX_SOURCE,
    STALE_FATAL_DAYS,
    STALE_WARN_DAYS,
    FxFetchError,
    FxRate,
    FxStaleError,
    _fx_cache_path,
    _read_fx_cache,
    _write_fx_cache,
    get_usd_to_krw_rate,
    try_get_usd_to_krw_rate,
)


def _success_payload(krw: float = 1378.5) -> dict[str, object]:
    return {
        "result": "success",
        "base_code": "USD",
        "rates": {"KRW": krw, "EUR": 0.9, "JPY": 155.0},
        "time_last_update_utc": "2026-05-27T00:00:00+00:00",
    }


def test_fx_rate_basis_string() -> None:
    fx = FxRate(
        base="USD",
        target="KRW",
        rate=1378.5,
        fetched_at=datetime(2026, 5, 27, tzinfo=UTC),
    )
    assert fx.basis_string() == f"{FX_SOURCE}:2026-05-27"


def test_cache_path_layout(tmp_path: Path) -> None:
    p = _fx_cache_path(date(2026, 5, 27), root=tmp_path)
    assert p == tmp_path / "2026-05-27.json"


def test_write_and_read_cache_roundtrip(tmp_path: Path) -> None:
    payload = _success_payload(krw=1380.0)
    p = _write_fx_cache(payload, date(2026, 5, 27), root=tmp_path)
    assert p.exists()
    assert _read_fx_cache(date(2026, 5, 27), root=tmp_path) == payload


def test_read_cache_missing_returns_none(tmp_path: Path) -> None:
    assert _read_fx_cache(date(2099, 1, 1), root=tmp_path) is None


def test_get_rate_uses_today_cache_no_remote(tmp_path: Path) -> None:
    """오늘 cache 가 있으면 remote fetch 안 함 (TTL=1d)."""
    today = date(2026, 5, 27)
    _write_fx_cache(_success_payload(krw=1380.0), today, root=tmp_path)

    with patch("anvyc.core.cost.fx._fetch_remote") as mock_fetch:
        rate = get_usd_to_krw_rate(today=today, cache_root=tmp_path)

    assert mock_fetch.call_count == 0  # remote 호출 0건
    assert rate.rate == 1380.0
    assert rate.is_stale is False
    assert rate.cache_age_days == 0


def test_get_rate_fetches_when_cache_absent(tmp_path: Path) -> None:
    """cache 부재 — remote fetch + 캐시 저장."""
    today = date(2026, 5, 27)

    with patch(
        "anvyc.core.cost.fx._fetch_remote",
        return_value=_success_payload(krw=1379.0),
    ):
        rate = get_usd_to_krw_rate(today=today, cache_root=tmp_path)

    assert rate.rate == 1379.0
    assert rate.is_stale is False
    # cache 저장됨
    assert _read_fx_cache(today, root=tmp_path) is not None


def test_get_rate_fallback_to_recent_cache_when_remote_fails(
    tmp_path: Path,
) -> None:
    """remote 실패 + 7d 이내 cache → 사용 + is_stale=False."""
    today = date(2026, 5, 27)
    yesterday = today - timedelta(days=3)
    _write_fx_cache(
        _success_payload(krw=1375.0), yesterday, root=tmp_path
    )

    with patch(
        "anvyc.core.cost.fx._fetch_remote",
        side_effect=FxFetchError("network down"),
    ):
        rate = get_usd_to_krw_rate(today=today, cache_root=tmp_path)

    assert rate.rate == 1375.0
    assert rate.is_stale is False
    assert rate.cache_age_days == 3


def test_get_rate_marks_stale_when_cache_over_warn(tmp_path: Path) -> None:
    """remote 실패 + cache 8d (warn 7d 초과, fatal 14d 미만) → is_stale=True."""
    today = date(2026, 5, 27)
    old = today - timedelta(days=STALE_WARN_DAYS + 1)
    _write_fx_cache(_success_payload(krw=1370.0), old, root=tmp_path)

    with patch(
        "anvyc.core.cost.fx._fetch_remote",
        side_effect=FxFetchError("network down"),
    ):
        rate = get_usd_to_krw_rate(today=today, cache_root=tmp_path)

    assert rate.rate == 1370.0
    assert rate.is_stale is True
    assert rate.cache_age_days == STALE_WARN_DAYS + 1


def test_get_rate_raises_stale_when_over_fatal(tmp_path: Path) -> None:
    """remote 실패 + cache 15d (fatal 14d 초과) → FxStaleError."""
    today = date(2026, 5, 27)
    too_old = today - timedelta(days=STALE_FATAL_DAYS + 1)
    _write_fx_cache(_success_payload(krw=1300.0), too_old, root=tmp_path)

    with patch(
        "anvyc.core.cost.fx._fetch_remote",
        side_effect=FxFetchError("network down"),
    ), pytest.raises(FxStaleError):
        get_usd_to_krw_rate(today=today, cache_root=tmp_path)


def test_get_rate_raises_fetch_when_no_cache_no_remote(tmp_path: Path) -> None:
    today = date(2026, 5, 27)
    with patch(
        "anvyc.core.cost.fx._fetch_remote",
        side_effect=FxFetchError("network down"),
    ), pytest.raises(FxFetchError):
        get_usd_to_krw_rate(today=today, cache_root=tmp_path)


def test_try_get_rate_returns_none_on_failure(tmp_path: Path) -> None:
    """try_get_* graceful — fetch / stale 둘 다 None."""
    today = date(2026, 5, 27)
    with patch(
        "anvyc.core.cost.fx._fetch_remote",
        side_effect=FxFetchError("down"),
    ):
        assert try_get_usd_to_krw_rate(today=today, cache_root=tmp_path) is None


def test_force_refresh_bypasses_today_cache(tmp_path: Path) -> None:
    """force_refresh=True 일 때 오늘 cache 있어도 remote 호출."""
    today = date(2026, 5, 27)
    _write_fx_cache(_success_payload(krw=1380.0), today, root=tmp_path)

    with patch(
        "anvyc.core.cost.fx._fetch_remote",
        return_value=_success_payload(krw=1399.0),
    ) as mock_fetch:
        rate = get_usd_to_krw_rate(
            today=today, cache_root=tmp_path, force_refresh=True
        )

    assert mock_fetch.call_count == 1
    assert rate.rate == 1399.0  # 새 fetch 값
