"""Unit tests for anvyc.core.cost.api helpers (CP-13 PR-13B1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anvyc.core.cost.api import (
    InvalidPeriodSpecError,
    UnknownSourceError,
    resolve_period,
    summarize_reports,
)
from anvyc.core.cost.ledger import (
    BreakdownItem,
    CostReport,
    CostReportMeta,
    Period,
)


def _mk_report(
    source: str,
    account: str,
    amount: float,
    *,
    model_breakdown: dict[str, float] | None = None,
    pricing_version: int | None = 1,
) -> CostReport:
    return CostReport(
        source=source,
        account=account,
        period=Period(
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        ),
        amount=amount,
        breakdown=[
            BreakdownItem(dim="model", key=m, amount=a)
            for m, a in (model_breakdown or {}).items()
        ],
        meta=CostReportMeta(pricing_version=pricing_version),
    )


# -- resolve_period -----------------------------------------------------------


def test_resolve_period_mtd() -> None:
    now = datetime(2026, 5, 15, 10, 30, tzinfo=UTC)
    p = resolve_period("mtd", now=now)
    assert p.start == datetime(2026, 5, 1, tzinfo=UTC)
    assert p.end == now


def test_resolve_period_yyyy_mm() -> None:
    p = resolve_period("2026-05")
    assert p.start == datetime(2026, 5, 1, tzinfo=UTC)
    assert p.end == datetime(2026, 6, 1, tzinfo=UTC)


def test_resolve_period_december_wraps() -> None:
    p = resolve_period("2026-12")
    assert p.start == datetime(2026, 12, 1, tzinfo=UTC)
    assert p.end == datetime(2027, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "spec",
    ["abc", "2026", "2026-13", "2026-00", "2026/05", "20260501"],
)
def test_resolve_period_invalid_raises(spec: str) -> None:
    with pytest.raises(InvalidPeriodSpecError):
        resolve_period(spec)


def test_resolve_period_naive_now_coerced_to_utc() -> None:
    """naive now 는 UTC 로 간주."""
    naive = datetime(2026, 5, 15, 10, 30)
    p = resolve_period("mtd", now=naive)
    assert p.start.tzinfo == UTC
    assert p.end.tzinfo == UTC


# -- summarize_reports --------------------------------------------------------


def test_summarize_empty_reports() -> None:
    s = summarize_reports([])
    assert s["total_amount_usd"] == 0.0
    assert s["currency"] == "USD"
    assert s["by_source"] == {}
    assert s["by_account"] == {}
    assert s["by_model"] == {}
    assert s["pricing_versions_seen"] == []
    assert s["report_count"] == 0


def test_summarize_aggregates_across_sources_accounts_models() -> None:
    reports = [
        _mk_report(
            "anthropic",
            "default",
            5.0,
            model_breakdown={"claude-opus-4-7": 5.0},
        ),
        _mk_report(
            "anthropic",
            "edward",
            3.0,
            model_breakdown={
                "claude-opus-4-7": 2.0,
                "claude-sonnet-4-6": 1.0,
            },
        ),
    ]
    s = summarize_reports(reports)
    assert s["total_amount_usd"] == pytest.approx(8.0)
    assert s["by_source"] == {"anthropic": pytest.approx(8.0)}
    assert s["by_account"] == {
        "anthropic:default": pytest.approx(5.0),
        "anthropic:edward": pytest.approx(3.0),
    }
    assert s["by_model"] == {
        "claude-opus-4-7": pytest.approx(7.0),
        "claude-sonnet-4-6": pytest.approx(1.0),
    }
    assert s["pricing_versions_seen"] == [1]
    assert s["report_count"] == 2


def test_summarize_pricing_versions_unique() -> None:
    reports = [
        _mk_report("anthropic", "default", 1.0, pricing_version=1),
        _mk_report("anthropic", "edward", 1.0, pricing_version=2),
        _mk_report("anthropic", "jklee", 1.0, pricing_version=1),
    ]
    s = summarize_reports(reports)
    assert s["pricing_versions_seen"] == [1, 2]


def test_summarize_ignores_non_model_breakdown() -> None:
    """dim != 'model' breakdown 은 by_model 에 안 들어감."""
    r = CostReport(
        source="aws",
        account="prod",
        period=Period(
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        ),
        amount=100.0,
        breakdown=[
            BreakdownItem(dim="service", key="ec2", amount=80.0),
            BreakdownItem(dim="service", key="s3", amount=20.0),
        ],
    )
    s = summarize_reports([r])
    assert s["by_model"] == {}
    assert s["by_source"]["aws"] == pytest.approx(100.0)


def test_unknown_source_error() -> None:
    """UnknownSourceError 메시지 + 속성."""
    e = UnknownSourceError("xyz", ["anthropic", "aws"])
    assert e.source == "xyz"
    assert "xyz" in str(e)
    assert e.known == ["anthropic", "aws"]
