"""Unit tests for anvyc.core.cost.compute (CP-13 PR-13A)."""

from __future__ import annotations

import pytest

from anvyc.core.cost.compute import compute_turn_cost, extract_normalized_usage
from anvyc.core.cost.pricing import load_pricing

# -- extract_normalized_usage --------------------------------------------------


def test_extract_usage_with_cache_creation_object() -> None:
    """`cache_creation.ephemeral_{5m,1h}` 두 sub-key 가 있으면 분리 사용."""
    msg = {
        "model": "claude-opus-4-7",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 2000,
            "cache_creation_input_tokens": 3000,  # legacy 합산값
            "cache_creation": {
                "ephemeral_5m_input_tokens": 1000,
                "ephemeral_1h_input_tokens": 2000,
            },
        },
    }
    out = extract_normalized_usage(msg)
    assert out == {
        "input": 100,
        "output": 50,
        "cache_read": 2000,
        "cache_write_5m": 1000,
        "cache_write_1h": 2000,
    }


def test_extract_usage_legacy_fallback() -> None:
    """`cache_creation` object 부재 시 cache_creation_input_tokens 를 5m 로."""
    msg = {
        "model": "claude-sonnet-4-6",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_creation_input_tokens": 500,
            # cache_read, cache_creation object 둘 다 없음
        },
    }
    out = extract_normalized_usage(msg)
    assert out is not None
    assert out["cache_write_5m"] == 500
    assert out["cache_write_1h"] == 0
    assert out["cache_read"] == 0


def test_extract_usage_missing_usage() -> None:
    assert extract_normalized_usage({"model": "x"}) is None
    assert extract_normalized_usage({"usage": "not-a-dict"}) is None


def test_extract_usage_non_dict_message() -> None:
    assert extract_normalized_usage(None) is None
    assert extract_normalized_usage("string") is None
    assert extract_normalized_usage([]) is None


def test_extract_usage_invalid_token_values() -> None:
    """token 값이 string / bool / None 등이면 0 으로 graceful."""
    msg = {
        "usage": {
            "input_tokens": "not-a-number",
            "output_tokens": True,  # bool 은 int 가 아니라 0
            "cache_read_input_tokens": None,
        }
    }
    out = extract_normalized_usage(msg)
    assert out == {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
    }


def test_extract_usage_float_tokens_coerced() -> None:
    """float token (드물지만 가능) 은 int cast."""
    msg = {"usage": {"input_tokens": 100.7, "output_tokens": 50.0}}
    out = extract_normalized_usage(msg)
    assert out is not None
    assert out["input"] == 100  # 0.7 truncated
    assert out["output"] == 50


# -- compute_turn_cost ---------------------------------------------------------


def test_compute_turn_cost_opus_47() -> None:
    """Opus 4.7 의 정확한 cost 계산.

    input=100, output=50, cache_write_5m=1000, cache_write_1h=2000, cache_read=2000
    가격: input=$5/MTok, output=$25/MTok, cache_write_5m=$6.25, cache_write_1h=$10, cache_read=$0.50
    """
    pricing = load_pricing()
    usage = {
        "input": 100,
        "output": 50,
        "cache_write_5m": 1000,
        "cache_write_1h": 2000,
        "cache_read": 2000,
    }
    cost = compute_turn_cost("claude-opus-4-7", usage, pricing)
    expected = (
        100 * (5.00 / 1_000_000)
        + 50 * (25.00 / 1_000_000)
        + 1000 * (6.25 / 1_000_000)
        + 2000 * (10.00 / 1_000_000)
        + 2000 * (0.50 / 1_000_000)
    )
    assert cost == pytest.approx(expected, rel=1e-9)


def test_compute_turn_cost_zero_tokens_skipped() -> None:
    """0 token 은 unit lookup 호출 안 함 — graceful, 0 cost."""
    pricing = load_pricing()
    usage = {
        "input": 0,
        "output": 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "cache_read": 0,
    }
    cost = compute_turn_cost("claude-opus-4-7", usage, pricing)
    assert cost == pytest.approx(0.0)


def test_compute_turn_cost_unknown_model_returns_none() -> None:
    """모델이 pricing table 에 없으면 None (graceful skip)."""
    pricing = load_pricing()
    usage = {"input": 100, "output": 50, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0}
    cost = compute_turn_cost("claude-future-x-1", usage, pricing)
    assert cost is None


def test_compute_turn_cost_deprecated_model_still_computed() -> None:
    """deprecated 모델 — historical cost 계산용 유지 (yaml deprecated_models)."""
    pricing = load_pricing()
    usage = {"input": 1000, "output": 0, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0}
    cost = compute_turn_cost("claude-opus-4", usage, pricing)
    # Opus 4 (deprecated) input = $15/MTok
    assert cost == pytest.approx(1000 * 15.0 / 1_000_000, rel=1e-9)
