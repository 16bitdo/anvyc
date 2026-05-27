"""Pricing SoT loader (CP-13 PR-13A0).

Reads `pricing/anthropic.yaml` and exposes `unit_price_usd_per_token(model,
token_type)` for downstream cost calculation in PR-13A / PR-13B.

R9 mitigation: `pricing_version` 캡처가 `CostReport.meta.pricing_version` 로
전달되어 가격 변동 시 historical cost drift 검출 (DESIGN §38.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml

PRICING_DIR = Path(__file__).resolve().parent
PRICING_FILE = PRICING_DIR / "anthropic.yaml"

TokenType = Literal[
    "input", "output", "cache_write_5m", "cache_write_1h", "cache_read"
]


class UnknownModelError(ValueError):
    """가격표에 등록되지 않은 model id."""

    def __init__(self, model: str) -> None:
        super().__init__(f"unknown model in pricing table: {model!r}")
        self.model = model


class UnknownTokenTypeError(ValueError):
    """모델에 등록되지 않은 token_type (e.g. opus 에 batch token)."""

    def __init__(self, model: str, token_type: str) -> None:
        super().__init__(
            f"token_type {token_type!r} not priced for model {model!r}"
        )
        self.model = model
        self.token_type = token_type


@dataclass(frozen=True)
class PricingTable:
    """`anthropic.yaml` 의 in-memory 표현.

    `version` / `effective_date` / `source_url` 가 R9 mitigation 의 audit
    trail. `unit_price_usd_per_token` 는 deprecated/retired 모델 fallback
    포함 — historical session 의 cost 재계산 가능.
    """

    version: int
    effective_date: str
    source_url: str
    models: dict[str, dict[str, float]]
    deprecated_models: dict[str, dict[str, float]]

    def unit_price_usd_per_token(
        self, model: str, token_type: TokenType
    ) -> float:
        """모델·token type 별 단가 (USD per token).

        yaml 의 단가는 USD per MTok 이므로 1_000_000 으로 나눠 token 단위로 변환.
        현행 → deprecated 순서로 lookup.
        """
        table = self.models.get(model) or self.deprecated_models.get(model)
        if table is None:
            raise UnknownModelError(model)
        try:
            price_per_mtok = table[token_type]
        except KeyError as e:
            raise UnknownTokenTypeError(model, token_type) from e
        return price_per_mtok / 1_000_000.0


def load_pricing(path: Path | None = None) -> PricingTable:
    """yaml 을 read 해 `PricingTable` 반환.

    `path` 미지정 시 패키지 내장 `anthropic.yaml`. 테스트 / staging 가격표
    검증 시 외부 path 지정 가능.
    """
    src = path or PRICING_FILE
    with src.open(encoding="utf-8") as f:
        data = cast(dict[str, Any], yaml.safe_load(f))
    return PricingTable(
        version=int(data["version"]),
        effective_date=str(data["effective_date"]),
        source_url=str(data["source_url"]),
        models=cast(dict[str, dict[str, float]], data.get("models", {})),
        deprecated_models=cast(
            dict[str, dict[str, float]], data.get("deprecated_models", {})
        ),
    )
