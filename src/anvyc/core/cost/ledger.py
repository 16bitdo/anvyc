"""CostReport schema v1 (CP-13 PR-13B1).

ADR v6-CP-13 §4.2.1 / DESIGN §38.2 본문. `schema_version=1` 합의 (CP-3
health / CP-4 snapshot / CP-5 creds / CP-6 sync 와 동일). 확장-호환만
허용 — 기존 키 변경 금지.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Account:
    """`source × key` 1차 식별자.

    `key` 의미 = source 별 다름:
      - anthropic: profile 명 (`default` / `edward` / `jklee`)
      - aws:       aws_profile 명
      - github:    gh login 명
    """

    source: str
    key: str


@dataclass(frozen=True)
class Period:
    """UTC 시각 범위 (start inclusive, end exclusive)."""

    start: datetime
    end: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Period:
        return cls(
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]),
        )


@dataclass(frozen=True)
class BreakdownItem:
    """차원별 분해 entry.

    `dim` = open string. 권장 enum (B2): `model / service / repo / workflow /
    tag / sku / cache_tier`. yaml/JSON 직렬화 시 단순 (dim, key, amount).
    """

    dim: str
    key: str
    amount: float


@dataclass
class CostReportMeta:
    """meta dict — source 별 자유. 공통 reserved 3 키:
    `measurement_cost_usd` / `pricing_version` / `org_id`. extra 는 source
    별 추가 키 (예: anthropic 의 `session_count`).
    """

    measurement_cost_usd: float = 0.0
    pricing_version: int | None = None
    org_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "measurement_cost_usd": self.measurement_cost_usd,
            "pricing_version": self.pricing_version,
            "org_id": self.org_id,
        }
        out.update(self.extra)
        return out


@dataclass
class CostReport:
    """CP-13 의 통합 cost data point.

    JSON serializable. `from_dict` 가 cache read / cross-machine sync 채널의
    역방향 — 확장-호환 (모르는 키는 meta.extra 로 보존).
    """

    source: str
    account: str
    period: Period
    amount: float
    currency: str = "USD"
    breakdown: list[BreakdownItem] = field(default_factory=list)
    collected_at: datetime | None = None
    fx_rate_basis: str | None = None
    meta: CostReportMeta = field(default_factory=CostReportMeta)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "account": self.account,
            "period": self.period.to_dict(),
            "currency": self.currency,
            "amount": self.amount,
            "breakdown": [
                {"dim": b.dim, "key": b.key, "amount": b.amount}
                for b in self.breakdown
            ],
            "collected_at": (
                self.collected_at.isoformat() if self.collected_at else None
            ),
            "fx_rate_basis": self.fx_rate_basis,
            "meta": self.meta.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostReport:
        meta_data = dict(data.get("meta", {}))
        reserved_measurement = float(
            meta_data.pop("measurement_cost_usd", 0.0)
        )
        reserved_pricing = meta_data.pop("pricing_version", None)
        reserved_org = meta_data.pop("org_id", None)
        collected = data.get("collected_at")
        return cls(
            source=str(data["source"]),
            account=str(data["account"]),
            period=Period.from_dict(data["period"]),
            currency=str(data.get("currency", "USD")),
            amount=float(data["amount"]),
            breakdown=[
                BreakdownItem(
                    dim=str(b["dim"]),
                    key=str(b["key"]),
                    amount=float(b["amount"]),
                )
                for b in data.get("breakdown", [])
            ],
            collected_at=(
                datetime.fromisoformat(collected) if collected else None
            ),
            fx_rate_basis=data.get("fx_rate_basis"),
            meta=CostReportMeta(
                measurement_cost_usd=reserved_measurement,
                pricing_version=(
                    int(reserved_pricing)
                    if reserved_pricing is not None
                    else None
                ),
                org_id=(
                    str(reserved_org) if reserved_org is not None else None
                ),
                extra=meta_data,
            ),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )


__all__ = [
    "SCHEMA_VERSION",
    "Account",
    "BreakdownItem",
    "CostReport",
    "CostReportMeta",
    "Period",
]
