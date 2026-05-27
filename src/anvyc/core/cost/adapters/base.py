"""CostAdapter Protocol (CP-13 PR-13B1).

ADR v6-CP-13 §4.2.1 / DESIGN §38.3 본문. source 별 (anthropic / aws / github)
cost 수집의 공통 인터페이스.

graceful skip 패턴 (ADR R11): optional dep 부재 시 `CostAdapterDepMissingError`
raise → 상위 caller catch + doctor `cost-<src>-dep-missing` WARNING.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from anvyc.core.cost.ledger import Account, CostReport, Period


@runtime_checkable
class CostAdapter(Protocol):
    """source 별 cost 수집 어댑터.

    `name` = source 식별자 (예: "anthropic"). `optional_dep_group` =
    `None` (core dep 만) 또는 "cost-aws" 같은 pip extras group.
    """

    name: str
    optional_dep_group: str | None

    def discover_accounts(self) -> Iterator[Account]:
        """본 어댑터가 발견한 모든 account 의 iterator."""
        ...

    def fetch_period(self, account: Account, period: Period) -> CostReport:
        """단일 account / period 의 CostReport 생성 (캐시 layer 아래)."""
        ...

    def supports_realtime(self) -> bool:
        """(i) 채널이 MTD 실시간 측정 지원 여부."""
        ...


class CostAdapterDepMissingError(RuntimeError):
    """optional dep 부재 graceful skip — doctor `cost-<src>-dep-missing` 이 catch."""

    def __init__(self, source: str, group: str) -> None:
        super().__init__(
            f"cost adapter {source!r} requires optional dep group {group!r}; "
            f"install with: pip install 'anvyc[{group}]'"
        )
        self.source = source
        self.group = group


__all__ = ["CostAdapter", "CostAdapterDepMissingError"]
