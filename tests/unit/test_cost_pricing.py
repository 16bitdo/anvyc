"""Unit tests for anvyc.core.cost.pricing.loader (CP-13 PR-13A0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core.cost.pricing import (
    UnknownModelError,
    UnknownTokenTypeError,
    load_pricing,
)


def test_load_default_pricing_table_basic_fields() -> None:
    """패키지 내장 anthropic.yaml load + 메타 필드 검증."""
    table = load_pricing()
    assert table.version >= 1
    assert table.effective_date  # ISO date string
    assert table.source_url.startswith("https://")
    # 현행 모델 3 시리즈 등록 확인
    assert "claude-opus-4-7" in table.models
    assert "claude-sonnet-4-6" in table.models
    assert "claude-haiku-4-5" in table.models


@pytest.mark.parametrize(
    "model,token_type,expected_per_mtok",
    [
        # Opus 4.7 — 4.5 시리즈 단가 (Opus 4.1 의 1/3)
        ("claude-opus-4-7", "input", 5.00),
        ("claude-opus-4-7", "output", 25.00),
        ("claude-opus-4-7", "cache_write_5m", 6.25),
        ("claude-opus-4-7", "cache_write_1h", 10.00),
        ("claude-opus-4-7", "cache_read", 0.50),
        # Sonnet 4.6
        ("claude-sonnet-4-6", "input", 3.00),
        ("claude-sonnet-4-6", "output", 15.00),
        ("claude-sonnet-4-6", "cache_read", 0.30),
        # Haiku 4.5
        ("claude-haiku-4-5", "input", 1.00),
        ("claude-haiku-4-5", "output", 5.00),
        ("claude-haiku-4-5", "cache_read", 0.10),
        # Opus 4.1 — 4.5 시리즈와 다른 단가 (3x premium)
        ("claude-opus-4-1", "input", 15.00),
        ("claude-opus-4-1", "output", 75.00),
    ],
)
def test_unit_price_known_models(
    model: str, token_type: str, expected_per_mtok: float
) -> None:
    """현행 모델 단가 정확성 — yaml SoT 검증 (가격 갱신 시 본 test 가 가장 먼저 fail)."""
    table = load_pricing()
    expected_per_token = expected_per_mtok / 1_000_000.0
    actual = table.unit_price_usd_per_token(model, token_type)  # type: ignore[arg-type]
    assert actual == pytest.approx(expected_per_token, rel=1e-9)


def test_deprecated_models_still_priced() -> None:
    """deprecated/retired 모델 — historical session cost 계산을 위해 유지."""
    table = load_pricing()
    # Opus 4 (deprecated) 은 4.1 과 동일 단가
    assert table.unit_price_usd_per_token(
        "claude-opus-4", "input"
    ) == pytest.approx(15.00 / 1_000_000.0, rel=1e-9)
    # Haiku 3.5 (retired except Bedrock/Vertex)
    assert table.unit_price_usd_per_token(
        "claude-haiku-3-5", "output"
    ) == pytest.approx(4.00 / 1_000_000.0, rel=1e-9)


def test_unknown_model_raises() -> None:
    table = load_pricing()
    with pytest.raises(UnknownModelError) as exc_info:
        table.unit_price_usd_per_token(
            "not-a-real-model", "input"
        )
    assert exc_info.value.model == "not-a-real-model"


def test_unknown_token_type_raises() -> None:
    table = load_pricing()
    with pytest.raises(UnknownTokenTypeError) as exc_info:
        table.unit_price_usd_per_token(
            "claude-opus-4-7", "nonexistent"  # type: ignore[arg-type]
        )
    assert exc_info.value.model == "claude-opus-4-7"
    assert exc_info.value.token_type == "nonexistent"


def test_custom_path_load(tmp_path: Path) -> None:
    """외부 path 의 yaml load — 향후 staging 가격표 / test 시."""
    custom = tmp_path / "custom.yaml"
    custom.write_text(
        """
version: 99
effective_date: "2099-01-01"
source_url: "https://example.com/test-pricing"
schema_version: 1
models:
  test-model:
    input: 42.0
    output: 84.0
""",
        encoding="utf-8",
    )
    table = load_pricing(path=custom)
    assert table.version == 99
    assert table.effective_date == "2099-01-01"
    assert table.unit_price_usd_per_token(
        "test-model", "input"
    ) == pytest.approx(42.0 / 1_000_000.0, rel=1e-9)


def test_pricing_table_is_frozen() -> None:
    """PricingTable 은 frozen dataclass — 외부 수정 차단."""
    import dataclasses

    table = load_pricing()
    with pytest.raises(dataclasses.FrozenInstanceError):
        table.version = 999  # type: ignore[misc]
