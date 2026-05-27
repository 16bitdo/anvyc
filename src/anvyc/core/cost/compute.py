"""Cost calculation helpers (CP-13 PR-13A).

Anthropic session jsonl 의 `message.usage` 를 normalize 후 token × pricing
으로 turn 별 USD cost 계산. `core/activity.py` 의 `parse_session` 이 본
모듈을 호출. Pricing SoT 는 `core/cost/pricing/anthropic.yaml` (PR-13A0).

R9 mitigation: `PricingTable.version` 캡처가 `Session.pricing_version` 로
전달되어 가격 변동 시 historical cost drift 검출 (DESIGN §38.2).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from anvyc.core.cost.pricing import (
    PricingTable,
    TokenType,
    UnknownModelError,
)

# Anthropic message.usage 의 외부 키. cache_creation.ephemeral_{5m,1h}
# 가 정확한 5m/1h 분리; legacy fallback 은 cache_creation_input_tokens
# 단일 값 (구 jsonl format).
_KEY_INPUT = "input_tokens"
_KEY_OUTPUT = "output_tokens"
_KEY_CACHE_READ = "cache_read_input_tokens"
_KEY_CACHE_CREATION_LEGACY = "cache_creation_input_tokens"
_KEY_CACHE_CREATION_OBJ = "cache_creation"
_SUBKEY_5M = "ephemeral_5m_input_tokens"
_SUBKEY_1H = "ephemeral_1h_input_tokens"

# Anvyc 내부 normalized key — pricing.TokenType 과 1:1 매핑.
_NORMALIZED_KEYS: tuple[TokenType, ...] = (
    "input",
    "output",
    "cache_write_5m",
    "cache_write_1h",
    "cache_read",
)


def extract_normalized_usage(message: Any) -> dict[str, int] | None:
    """Anthropic `message.usage` 를 anvyc 내부 표준 키 5종으로 normalize.

    반환 dict 키: `input` / `output` / `cache_write_5m` / `cache_write_1h` /
    `cache_read`. `usage` 부재 또는 형식 불일치 시 `None`.

    cache write 는 (a) `cache_creation.ephemeral_{5m,1h}_input_tokens` 두
    sub-key 가 있으면 분리 사용, (b) 없으면 legacy
    `cache_creation_input_tokens` 단일 값을 5m 로 fallback.
    """
    if not isinstance(message, Mapping):
        return None
    usage = message.get("usage")
    if not isinstance(usage, Mapping):
        return None

    out: dict[str, int] = {
        "input": _safe_int(usage.get(_KEY_INPUT)),
        "output": _safe_int(usage.get(_KEY_OUTPUT)),
        "cache_read": _safe_int(usage.get(_KEY_CACHE_READ)),
        "cache_write_5m": 0,
        "cache_write_1h": 0,
    }
    cache_obj = usage.get(_KEY_CACHE_CREATION_OBJ)
    if isinstance(cache_obj, Mapping):
        out["cache_write_5m"] = _safe_int(cache_obj.get(_SUBKEY_5M))
        out["cache_write_1h"] = _safe_int(cache_obj.get(_SUBKEY_1H))
    else:
        # legacy fallback — 5m/1h 구분 없을 때 cache_creation_input_tokens
        # 전체를 5m 로 (가장 흔한 단가). 1h-only 케이스는 under-estimate
        # 가능하나 R9 doctor reconciliation 이 검출.
        out["cache_write_5m"] = _safe_int(usage.get(_KEY_CACHE_CREATION_LEGACY))
    return out


def _safe_int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def compute_turn_cost(
    model: str,
    normalized_usage: dict[str, int],
    pricing: PricingTable,
) -> float | None:
    """단일 turn 의 cost (USD) 계산.

    `normalized_usage` 의 key 가 `pricing` 의 `TokenType` 과 1:1 매핑.
    모델이 pricing table 에 없으면 `None` (graceful skip — Session.cost_usd
    도 None 으로 전파; doctor `cost-pricing-stale` / `cost-anthropic-reconciliation`
    이 후속 검출).
    """
    try:
        total = 0.0
        for token_key, tokens in normalized_usage.items():
            if tokens <= 0:
                continue
            unit = pricing.unit_price_usd_per_token(
                model, cast(TokenType, token_key)
            )
            total += tokens * unit
        return total
    except UnknownModelError:
        return None


__all__ = [
    "compute_turn_cost",
    "extract_normalized_usage",
]
