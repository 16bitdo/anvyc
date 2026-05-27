"""Unit tests for anvyc.core.cost.ledger (CP-13 PR-13B1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anvyc.core.cost.ledger import (
    SCHEMA_VERSION,
    Account,
    BreakdownItem,
    CostReport,
    CostReportMeta,
    Period,
)


def test_schema_version_constant() -> None:
    """schema_version=1 — CP-3/4/5/6 와 합의."""
    assert SCHEMA_VERSION == 1


def test_period_roundtrip() -> None:
    p = Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )
    d = p.to_dict()
    assert d == {
        "start": "2026-05-01T00:00:00+00:00",
        "end": "2026-06-01T00:00:00+00:00",
    }
    assert Period.from_dict(d) == p


def test_cost_report_to_dict_full() -> None:
    r = CostReport(
        source="anthropic",
        account="edward",
        period=Period(
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        ),
        amount=123.456789,
        breakdown=[
            BreakdownItem(dim="model", key="claude-opus-4-7", amount=100.0),
            BreakdownItem(dim="model", key="claude-sonnet-4-6", amount=23.456789),
        ],
        collected_at=datetime(2026, 5, 27, 4, 0, tzinfo=UTC),
        meta=CostReportMeta(
            measurement_cost_usd=0.05,
            pricing_version=1,
            extra={"session_count": 42},
        ),
    )
    d = r.to_dict()
    assert d["schema_version"] == 1
    assert d["source"] == "anthropic"
    assert d["account"] == "edward"
    assert d["currency"] == "USD"
    assert d["amount"] == pytest.approx(123.456789)
    assert d["breakdown"] == [
        {"dim": "model", "key": "claude-opus-4-7", "amount": 100.0},
        {"dim": "model", "key": "claude-sonnet-4-6", "amount": 23.456789},
    ]
    assert d["meta"]["measurement_cost_usd"] == 0.05
    assert d["meta"]["pricing_version"] == 1
    assert d["meta"]["session_count"] == 42  # extra merged


def test_cost_report_roundtrip() -> None:
    """to_dict / from_dict 양방향 정합."""
    original = CostReport(
        source="anthropic",
        account="default",
        period=Period(
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 5, 27, tzinfo=UTC),
        ),
        amount=42.0,
        breakdown=[BreakdownItem(dim="model", key="claude-opus-4-7", amount=42.0)],
        collected_at=datetime(2026, 5, 27, tzinfo=UTC),
        meta=CostReportMeta(pricing_version=1, extra={"x": "y"}),
    )
    d = original.to_dict()
    restored = CostReport.from_dict(d)
    assert restored.source == original.source
    assert restored.account == original.account
    assert restored.period == original.period
    assert restored.amount == pytest.approx(original.amount)
    assert restored.breakdown == original.breakdown
    assert restored.collected_at == original.collected_at
    assert restored.meta.pricing_version == 1
    assert restored.meta.extra == {"x": "y"}


def test_cost_report_from_dict_minimal() -> None:
    """필수 키만 — 나머지는 default."""
    d = {
        "source": "anthropic",
        "account": "default",
        "period": {
            "start": "2026-05-01T00:00:00+00:00",
            "end": "2026-06-01T00:00:00+00:00",
        },
        "amount": 0.0,
    }
    r = CostReport.from_dict(d)
    assert r.currency == "USD"
    assert r.breakdown == []
    assert r.collected_at is None
    assert r.meta.measurement_cost_usd == 0.0
    assert r.meta.pricing_version is None
    assert r.schema_version == SCHEMA_VERSION


def test_account_is_hashable() -> None:
    """frozen dataclass — set / dict key 용."""
    s = {Account("anthropic", "edward"), Account("anthropic", "edward")}
    assert len(s) == 1


def test_breakdown_item_is_frozen() -> None:
    """frozen — 외부 mutation 차단."""
    import dataclasses

    b = BreakdownItem(dim="model", key="x", amount=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.amount = 99.0  # type: ignore[misc]
