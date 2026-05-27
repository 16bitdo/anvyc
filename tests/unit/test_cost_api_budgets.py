"""Unit tests for budget_evaluations in summary_payload (CP-13 PR-13E2)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from anvyc.core.cost.api import summary_payload
from anvyc.core.cost.cache import write_cache
from anvyc.core.cost.ledger import (
    BreakdownItem,
    CostReport,
    CostReportMeta,
    Period,
)


def _mk_report(
    source: str = "anthropic",
    account: str = "default",
    amount: float = 50.0,
    *,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> CostReport:
    today = date.today()  # noqa: DTZ011
    start = period_start or datetime(today.year, today.month, 1, tzinfo=UTC)
    if period_end is None:
        end = (
            datetime(today.year, today.month + 1, 1, tzinfo=UTC)
            if today.month < 12
            else datetime(today.year + 1, 1, 1, tzinfo=UTC)
        )
    else:
        end = period_end
    return CostReport(
        source=source,
        account=account,
        period=Period(start=start, end=end),
        amount=amount,
        breakdown=[
            BreakdownItem(dim="model", key="claude-opus-4-7", amount=amount)
        ],
        meta=CostReportMeta(pricing_version=1),
    )


def test_summary_payload_no_budgets_returns_empty_evaluations(
    tmp_path: Path,
) -> None:
    """budgets.yml 부재 → budget_evaluations: []."""
    today = date.today()  # noqa: DTZ011
    write_cache(_mk_report(), day=today, root=tmp_path)

    with patch("anvyc.core.cost.budgets.load_budgets", return_value=[]):
        s = summary_payload(period_spec="mtd", cache_root=tmp_path)

    assert "budget_evaluations" in s
    assert s["budget_evaluations"] == []


def test_summary_payload_with_budgets_returns_evaluations(
    tmp_path: Path,
) -> None:
    """budgets.yml 있음 → evaluations 채움."""
    from anvyc.core.cost.budgets import Budget

    today = date.today()  # noqa: DTZ011
    write_cache(_mk_report(amount=85.0), day=today, root=tmp_path)

    budgets = [
        Budget(
            source="anthropic",
            account="default",
            period="monthly",
            amount_usd=100.0,
            warn_pct=80.0,
            critical_pct=95.0,
        )
    ]

    with patch("anvyc.core.cost.budgets.load_budgets", return_value=budgets):
        s = summary_payload(period_spec="mtd", cache_root=tmp_path)

    assert len(s["budget_evaluations"]) == 1
    e = s["budget_evaluations"][0]
    assert e["source"] == "anthropic"
    assert e["account"] == "default"
    assert e["period"] == "monthly"
    assert e["amount_usd_limit"] == 100.0
    assert e["actual_usd"] == pytest.approx(85.0)
    assert e["usage_pct"] == pytest.approx(85.0)
    assert e["severity"] == "warn"


def test_summary_payload_budget_wildcard_aggregates(tmp_path: Path) -> None:
    """wildcard budget 이 여러 account 합산."""
    from anvyc.core.cost.budgets import Budget

    today = date.today()  # noqa: DTZ011
    write_cache(
        _mk_report("anthropic", "default", 40.0), day=today, root=tmp_path
    )
    write_cache(
        _mk_report("anthropic", "edward", 60.0), day=today, root=tmp_path
    )

    budgets = [
        Budget(
            source="anthropic",
            account="*",
            period="monthly",
            amount_usd=200.0,
        )
    ]

    with patch("anvyc.core.cost.budgets.load_budgets", return_value=budgets):
        s = summary_payload(period_spec="mtd", cache_root=tmp_path)

    assert len(s["budget_evaluations"]) == 1
    e = s["budget_evaluations"][0]
    assert e["actual_usd"] == pytest.approx(100.0)  # 40 + 60
    assert e["usage_pct"] == pytest.approx(50.0)
    assert e["severity"] == "ok"


def test_summary_payload_budget_critical_severity(tmp_path: Path) -> None:
    """≥ critical_pct → severity=critical."""
    from anvyc.core.cost.budgets import Budget

    today = date.today()  # noqa: DTZ011
    write_cache(_mk_report(amount=99.0), day=today, root=tmp_path)

    budgets = [
        Budget(
            source="anthropic",
            account="default",
            period="monthly",
            amount_usd=100.0,
            warn_pct=80.0,
            critical_pct=95.0,
        )
    ]

    with patch("anvyc.core.cost.budgets.load_budgets", return_value=budgets):
        s = summary_payload(period_spec="mtd", cache_root=tmp_path)

    assert s["budget_evaluations"][0]["severity"] == "critical"


def test_summary_payload_budget_load_error_returns_empty(
    tmp_path: Path,
) -> None:
    """budgets.yml load 실패 → graceful empty (서비스 중단 없음)."""
    today = date.today()  # noqa: DTZ011
    write_cache(_mk_report(), day=today, root=tmp_path)

    with patch(
        "anvyc.core.cost.budgets.load_budgets",
        side_effect=OSError("permission denied"),
    ):
        s = summary_payload(period_spec="mtd", cache_root=tmp_path)

    assert s["budget_evaluations"] == []
