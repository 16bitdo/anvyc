"""Unit tests for anvyc.core.cost.budgets (CP-13 PR-13B2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core.cost.budgets import (
    WILDCARD,
    Budget,
    BudgetSeverity,
    InvalidBudgetError,
    evaluate,
    load_budgets,
)


def test_load_budgets_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_budgets(tmp_path / "nope.yml") == []


def test_load_budgets_basic(tmp_path: Path) -> None:
    p = tmp_path / "budgets.yml"
    p.write_text(
        """
budgets:
  - source: anthropic
    account: edward
    period: monthly
    amount_usd: 100.0
    warn_pct: 80
    critical_pct: 95
  - source: '*'
    account: '*'
    period: monthly
    amount_usd: 500.0
""",
        encoding="utf-8",
    )
    bs = load_budgets(p)
    assert len(bs) == 2
    assert bs[0] == Budget(
        source="anthropic",
        account="edward",
        period="monthly",
        amount_usd=100.0,
        warn_pct=80.0,
        critical_pct=95.0,
    )
    assert bs[1].source == WILDCARD
    assert bs[1].account == WILDCARD


def test_load_budgets_defaults_pct(tmp_path: Path) -> None:
    p = tmp_path / "budgets.yml"
    p.write_text(
        """
budgets:
  - source: anthropic
    account: edward
    period: monthly
    amount_usd: 50.0
""",
        encoding="utf-8",
    )
    bs = load_budgets(p)
    assert bs[0].warn_pct == 80.0
    assert bs[0].critical_pct == 95.0


def test_load_budgets_empty_yml(tmp_path: Path) -> None:
    p = tmp_path / "budgets.yml"
    p.write_text("", encoding="utf-8")
    assert load_budgets(p) == []


def test_load_budgets_invalid_top_level(tmp_path: Path) -> None:
    p = tmp_path / "budgets.yml"
    p.write_text("- not a map", encoding="utf-8")
    with pytest.raises(InvalidBudgetError):
        load_budgets(p)


def test_load_budgets_invalid_entry(tmp_path: Path) -> None:
    p = tmp_path / "budgets.yml"
    p.write_text(
        """
budgets:
  - source: anthropic
    # account 누락
    period: monthly
    amount_usd: 100.0
""",
        encoding="utf-8",
    )
    with pytest.raises(InvalidBudgetError):
        load_budgets(p)


# -- matches -----------------------------------------------------------------


def test_budget_matches_exact() -> None:
    b = Budget(
        source="anthropic", account="edward", period="monthly", amount_usd=100.0
    )
    assert b.matches("anthropic", "edward") is True
    assert b.matches("anthropic", "jklee") is False
    assert b.matches("aws", "edward") is False


def test_budget_matches_wildcard() -> None:
    b = Budget(
        source="*", account="*", period="monthly", amount_usd=500.0
    )
    assert b.matches("anthropic", "edward") is True
    assert b.matches("aws", "prod") is True


# -- evaluate ----------------------------------------------------------------


def test_evaluate_ok() -> None:
    b = Budget(
        source="anthropic",
        account="edward",
        period="monthly",
        amount_usd=100.0,
    )
    actuals = {("anthropic", "edward"): 30.0}
    [eval_] = evaluate(actuals, [b])
    assert eval_.actual_usd == pytest.approx(30.0)
    assert eval_.usage_pct == pytest.approx(30.0)
    assert eval_.severity == BudgetSeverity.OK


def test_evaluate_warn() -> None:
    b = Budget(
        source="anthropic",
        account="edward",
        period="monthly",
        amount_usd=100.0,
        warn_pct=80.0,
        critical_pct=95.0,
    )
    actuals = {("anthropic", "edward"): 85.0}
    [eval_] = evaluate(actuals, [b])
    assert eval_.severity == BudgetSeverity.WARN


def test_evaluate_critical() -> None:
    b = Budget(
        source="anthropic",
        account="edward",
        period="monthly",
        amount_usd=100.0,
        warn_pct=80.0,
        critical_pct=95.0,
    )
    actuals = {("anthropic", "edward"): 105.0}
    [eval_] = evaluate(actuals, [b])
    assert eval_.usage_pct == pytest.approx(105.0)
    assert eval_.severity == BudgetSeverity.CRITICAL


def test_evaluate_wildcard_sums_matching_accounts() -> None:
    """wildcard budget — 여러 account 합산."""
    b = Budget(source="anthropic", account="*", period="monthly", amount_usd=100.0)
    actuals = {
        ("anthropic", "default"): 40.0,
        ("anthropic", "edward"): 35.0,
        ("aws", "prod"): 50.0,  # source 불일치 — 제외
    }
    [eval_] = evaluate(actuals, [b])
    assert eval_.actual_usd == pytest.approx(75.0)
    assert eval_.severity == BudgetSeverity.OK


def test_evaluate_no_match_actuals_zero() -> None:
    b = Budget(
        source="anthropic", account="edward", period="monthly", amount_usd=100.0
    )
    actuals = {("aws", "prod"): 99.0}  # 매칭 0
    [eval_] = evaluate(actuals, [b])
    assert eval_.actual_usd == pytest.approx(0.0)
    assert eval_.severity == BudgetSeverity.OK
