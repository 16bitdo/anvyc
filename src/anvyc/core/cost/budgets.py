"""Budgets (CP-13 PR-13B2).

`~/.config/anvyc/cost/budgets.yml` 의 예산 정책 loader + 임계 비교.
ADR §4.2.2 + DESIGN §38.7 (CP-3 scheduler 시너지) 의 wiring 은 PR-13E
에서 — 본 PR 은 schema + evaluate 만.

schema:
```yaml
budgets:
  - source: anthropic          # 또는 '*'
    account: edward            # 또는 '*'
    period: monthly            # monthly | daily
    amount_usd: 100.0
    warn_pct: 80               # 0~100
    critical_pct: 95
```
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

BUDGETS_FILE = Path.home() / ".config" / "anvyc" / "cost" / "budgets.yml"
WILDCARD = "*"


class BudgetSeverity(StrEnum):
    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Budget:
    source: str
    account: str
    period: str
    amount_usd: float
    warn_pct: float = 80.0
    critical_pct: float = 95.0

    def matches(self, src: str, acct: str) -> bool:
        """wildcard `'*'` = any."""
        if self.source != WILDCARD and self.source != src:
            return False
        return not (self.account != WILDCARD and self.account != acct)


@dataclass(frozen=True)
class BudgetEval:
    budget: Budget
    actual_usd: float
    usage_pct: float
    severity: BudgetSeverity


class InvalidBudgetError(ValueError):
    """budgets.yml schema 위반."""


def load_budgets(path: Path | None = None) -> list[Budget]:
    """yml read + Budget list 반환.

    파일 부재 시 빈 list (graceful — budgets 미설정도 정상 운영).
    """
    src = path or BUDGETS_FILE
    if not src.exists():
        return []
    try:
        with src.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise InvalidBudgetError(f"failed to load {src}: {e}") from e
    if data is None:
        return []
    if not isinstance(data, dict):
        raise InvalidBudgetError(f"top-level must be mapping: {src}")
    entries = data.get("budgets", [])
    if not isinstance(entries, list):
        raise InvalidBudgetError(f"'budgets' must be list: {src}")
    return [_parse_budget(e, src) for e in entries]


def _parse_budget(entry: Any, src: Path) -> Budget:
    if not isinstance(entry, dict):
        raise InvalidBudgetError(f"budget entry must be mapping: {entry!r}")
    try:
        return Budget(
            source=str(entry["source"]),
            account=str(entry["account"]),
            period=str(entry["period"]),
            amount_usd=float(entry["amount_usd"]),
            warn_pct=float(entry.get("warn_pct", 80.0)),
            critical_pct=float(entry.get("critical_pct", 95.0)),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise InvalidBudgetError(
            f"invalid budget entry in {src}: {entry!r} ({e})"
        ) from e


def evaluate(
    actuals: dict[tuple[str, str], float], budgets: list[Budget]
) -> list[BudgetEval]:
    """(source, account) → actual USD 의 합산값을 각 budget 과 비교.

    한 budget 이 여러 (source, account) 와 wildcard 매칭되면 합산. 매칭 0건이면
    `actual=0.0` 으로 평가 (under budget).
    """
    out: list[BudgetEval] = []
    for budget in budgets:
        matched_total = 0.0
        for (src, acct), amount in actuals.items():
            if budget.matches(src, acct):
                matched_total += amount
        pct = (
            (matched_total / budget.amount_usd * 100.0)
            if budget.amount_usd > 0
            else 0.0
        )
        if pct >= budget.critical_pct:
            sev = BudgetSeverity.CRITICAL
        elif pct >= budget.warn_pct:
            sev = BudgetSeverity.WARN
        else:
            sev = BudgetSeverity.OK
        out.append(
            BudgetEval(
                budget=budget,
                actual_usd=round(matched_total, 6),
                usage_pct=round(pct, 2),
                severity=sev,
            )
        )
    return out


__all__ = [
    "BUDGETS_FILE",
    "Budget",
    "BudgetEval",
    "BudgetSeverity",
    "InvalidBudgetError",
    "evaluate",
    "load_budgets",
]
