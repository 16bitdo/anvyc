"""Extended unit tests for anvyc.core.cost.api — gc / ledger / KRW (CP-13 PR-13B2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from anvyc.core.cost.api import (
    gc_raw_daily,
    ledger_rows,
    summary_payload,
)
from anvyc.core.cost.cache import write_cache
from anvyc.core.cost.fx import FxRate
from anvyc.core.cost.ledger import (
    BreakdownItem,
    CostReport,
    CostReportMeta,
    Period,
)


@pytest.fixture(autouse=True)
def _no_live_cost_collect(monkeypatch: pytest.MonkeyPatch) -> None:
    """hermeticity 보증 — summary_payload 의 cache-miss fallback 이 live adapter
    (boto3/httpx → AWS/GitHub network)를 절대 호출하지 않게 collect_and_persist 차단.

    gc/ledger 테스트는 collect 를 안 타므로 무영향. KRW 테스트는 cache 채워진 정상
    경로라 호출되지 않지만, 환경 의존(httpx 설치/실 자격) 시 network 대신 [] 반환.
    """
    monkeypatch.setattr(
        "anvyc.core.cost.api.collect_and_persist", lambda *a, **k: []
    )


def _utc_month_period() -> Period:
    """현재 UTC 월 [1일 0시, 다음 월 1일). resolve_period("mtd")(UTC now 기준)와
    교차 보장 — date.today()(로컬) 사용 시 KST 가 UTC 보다 앞선 시간대에 월이 어긋난다.
    """
    now = datetime.now(UTC)
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    end = (
        datetime(now.year + 1, 1, 1, tzinfo=UTC)
        if now.month == 12
        else datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    )
    return Period(start=start, end=end)


def _mk_report(
    source: str = "anthropic",
    account: str = "default",
    amount: float = 10.0,
) -> CostReport:
    return CostReport(
        source=source,
        account=account,
        period=Period(
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        ),
        amount=amount,
        breakdown=[BreakdownItem(dim="model", key="claude-opus-4-7", amount=amount)],
        meta=CostReportMeta(pricing_version=1),
    )


# -- gc_raw_daily ------------------------------------------------------------


def test_gc_removes_old_dry_run(tmp_path: Path) -> None:
    today = date(2026, 5, 27)
    # 100일 전 cache (90d 초과)
    old_day = today - timedelta(days=100)
    new_day = today - timedelta(days=30)
    write_cache(_mk_report(), day=old_day, root=tmp_path)
    write_cache(_mk_report(), day=new_day, root=tmp_path)

    result = gc_raw_daily(
        keep_days=90, cache_root=tmp_path, dry_run=True, today=today
    )
    assert result["dry_run"] is True
    assert result["removed_count"] == 1
    assert result["kept_count"] == 1
    # 실 파일은 그대로
    assert (
        tmp_path / "anthropic" / "default" / f"{old_day.isoformat()}.json"
    ).exists()


def test_gc_removes_old_apply(tmp_path: Path) -> None:
    today = date(2026, 5, 27)
    old_day = today - timedelta(days=100)
    new_day = today - timedelta(days=30)
    write_cache(_mk_report(), day=old_day, root=tmp_path)
    write_cache(_mk_report(), day=new_day, root=tmp_path)

    result = gc_raw_daily(
        keep_days=90, cache_root=tmp_path, dry_run=False, today=today
    )
    assert result["dry_run"] is False
    assert result["removed_count"] == 1
    # 실 파일 사라짐
    assert not (
        tmp_path / "anthropic" / "default" / f"{old_day.isoformat()}.json"
    ).exists()
    # 새 cache 는 남음
    assert (
        tmp_path / "anthropic" / "default" / f"{new_day.isoformat()}.json"
    ).exists()


def test_gc_keep_all_when_inside_retention(tmp_path: Path) -> None:
    today = date(2026, 5, 27)
    for d in range(5):
        write_cache(
            _mk_report(),
            day=today - timedelta(days=d * 10),
            root=tmp_path,
        )
    result = gc_raw_daily(
        keep_days=90, cache_root=tmp_path, dry_run=False, today=today
    )
    assert result["removed_count"] == 0
    assert result["kept_count"] == 5


# -- ledger_rows -------------------------------------------------------------


def test_ledger_rows_basic(tmp_path: Path) -> None:
    today = date(2026, 5, 27)
    write_cache(
        _mk_report("anthropic", "default", 5.0),
        day=today,
        root=tmp_path,
    )
    write_cache(
        _mk_report("anthropic", "edward", 3.0),
        day=today,
        root=tmp_path,
    )

    rows = ledger_rows(cache_root=tmp_path)
    assert len(rows) == 2
    accts = {r["account"] for r in rows}
    assert accts == {"default", "edward"}
    for r in rows:
        assert r["source"] == "anthropic"
        assert r["model_breakdown_count"] == 1
        assert r["pricing_version"] == 1
        assert "measurement_cost_usd" not in r  # default off


def test_ledger_rows_filters(tmp_path: Path) -> None:
    today = date(2026, 5, 27)
    write_cache(_mk_report("anthropic", "default"), day=today, root=tmp_path)
    write_cache(_mk_report("anthropic", "edward"), day=today, root=tmp_path)

    rows = ledger_rows(account="edward", cache_root=tmp_path)
    assert len(rows) == 1
    assert rows[0]["account"] == "edward"


def test_ledger_rows_include_meta(tmp_path: Path) -> None:
    today = date(2026, 5, 27)
    write_cache(_mk_report(), day=today, root=tmp_path)

    rows = ledger_rows(include_meta=True, cache_root=tmp_path)
    assert "measurement_cost_usd" in rows[0]
    assert "org_id" in rows[0]
    assert "collected_at" in rows[0]


# -- summary_payload KRW -----------------------------------------------------


def test_summary_payload_includes_krw_when_fx_available(tmp_path: Path) -> None:
    """fx 가용 시 total_amount_krw 포함."""
    fx = FxRate(
        base="USD",
        target="KRW",
        rate=1378.0,
        fetched_at=datetime(2026, 5, 27, tzinfo=UTC),
    )

    # cache 1건 추가 (mtd period 안에 들도록 collected_at 조정 불필요 — period
    # filter 는 r.period 기준).
    today = date.today()  # noqa: DTZ011 — local today OK for test
    write_cache(
        CostReport(
            source="anthropic",
            account="default",
            period=_utc_month_period(),
            amount=100.0,
            breakdown=[],
            meta=CostReportMeta(pricing_version=1),
        ),
        day=today,
        root=tmp_path,
    )

    with patch(
        "anvyc.core.cost.fx.try_get_usd_to_krw_rate", return_value=fx
    ):
        s = summary_payload(period_spec="mtd", cache_root=tmp_path)

    assert s["total_amount_usd"] == pytest.approx(100.0)
    assert s["total_amount_krw"] == pytest.approx(137800.0)
    assert s["fx_rate_basis"] == "open.er-api.com:2026-05-27"
    assert s["fx_stale"] is False


def test_summary_payload_krw_none_when_fx_unavailable(tmp_path: Path) -> None:
    """fx 실패 시 KRW 필드 모두 None — graceful USD only."""
    today = date.today()  # noqa: DTZ011
    write_cache(
        CostReport(
            source="anthropic",
            account="default",
            period=_utc_month_period(),
            amount=50.0,
            breakdown=[],
        ),
        day=today,
        root=tmp_path,
    )

    with patch(
        "anvyc.core.cost.fx.try_get_usd_to_krw_rate", return_value=None
    ):
        s = summary_payload(period_spec="mtd", cache_root=tmp_path)

    assert s["total_amount_usd"] == pytest.approx(50.0)
    assert s["total_amount_krw"] is None
    assert s["fx_rate_basis"] is None
    assert s["fx_stale"] is None


def test_summary_payload_include_krw_false_skips_fx(tmp_path: Path) -> None:
    """include_krw=False 시 fx 호출 안 함."""
    today = date.today()  # noqa: DTZ011
    write_cache(
        CostReport(
            source="anthropic",
            account="default",
            period=_utc_month_period(),
            amount=42.0,
            breakdown=[],
        ),
        day=today,
        root=tmp_path,
    )

    with patch(
        "anvyc.core.cost.fx.try_get_usd_to_krw_rate"
    ) as mock_fx:
        s = summary_payload(
            period_spec="mtd", cache_root=tmp_path, include_krw=False
        )

    assert mock_fx.call_count == 0
    assert "total_amount_krw" not in s
