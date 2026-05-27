"""Integration test for cost dimension wired into Session / aggregate (CP-13 PR-13A)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anvyc.core.activity import (
    Session,
    aggregate_sessions,
    parse_session,
)


def _write_jsonl(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


def _assistant_event(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read: int = 0,
    cache_write_5m: int = 0,
    cache_write_1h: int = 0,
    tool_uses: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": cache_write_5m,
                    "ephemeral_1h_input_tokens": cache_write_1h,
                },
            },
            "content": [
                {"type": "tool_use", "name": n} for n in tool_uses
            ],
        },
    }


def test_parse_session_populates_cost_dimension(tmp_path: Path) -> None:
    """Opus 4.7 한 turn — cost_usd / tokens_* / cost_by_model_usd / pricing_version."""
    p = tmp_path / "s.jsonl"
    _write_jsonl(
        p,
        [
            {"sessionId": "S1", "cwd": "/tmp", "timestamp": "2026-05-27T00:00:00Z"},
            _assistant_event(
                "claude-opus-4-7",
                input_tokens=100,
                output_tokens=50,
                cache_read=2000,
                cache_write_5m=1000,
                cache_write_1h=2000,
            ),
        ],
    )
    sess = parse_session(p)
    assert sess is not None
    assert sess.session_id == "S1"
    assert sess.tokens_in == 100
    assert sess.tokens_out == 50
    assert sess.tokens_cache_read == 2000
    assert sess.tokens_cache_write_5m == 1000
    assert sess.tokens_cache_write_1h == 2000
    # 가격 계산: 100*5 + 50*25 + 2000*0.5 + 1000*6.25 + 2000*10 = 500+1250+1000+6250+20000 = 29000
    # USD = 29000 / 1_000_000 = 0.029
    assert sess.cost_usd == pytest.approx(0.029, rel=1e-6)
    assert sess.cost_by_model_usd == {
        "claude-opus-4-7": pytest.approx(0.029, rel=1e-6)
    }
    assert sess.pricing_version == 1


def test_parse_session_multiple_models_cost_split(tmp_path: Path) -> None:
    """한 session 안에서 model 이 바뀌면 cost_by_model_usd 가 분해."""
    p = tmp_path / "multi.jsonl"
    _write_jsonl(
        p,
        [
            {"sessionId": "M1", "timestamp": "2026-05-27T00:00:00Z"},
            _assistant_event("claude-opus-4-7", input_tokens=1_000_000),  # = $5
            _assistant_event("claude-sonnet-4-6", input_tokens=1_000_000),  # = $3
        ],
    )
    sess = parse_session(p)
    assert sess is not None
    assert sess.tokens_in == 2_000_000
    assert sess.cost_usd == pytest.approx(8.0, rel=1e-9)
    assert sess.cost_by_model_usd == {
        "claude-opus-4-7": pytest.approx(5.0, rel=1e-9),
        "claude-sonnet-4-6": pytest.approx(3.0, rel=1e-9),
    }


def test_parse_session_unknown_model_graceful(tmp_path: Path) -> None:
    """pricing 미인식 모델 — token 만 누적, cost_usd 는 None 유지."""
    p = tmp_path / "unknown.jsonl"
    _write_jsonl(
        p,
        [
            {"sessionId": "U1", "timestamp": "2026-05-27T00:00:00Z"},
            _assistant_event("claude-future-x-1", input_tokens=500, output_tokens=200),
        ],
    )
    sess = parse_session(p)
    assert sess is not None
    # token 은 누적
    assert sess.tokens_in == 500
    assert sess.tokens_out == 200
    # cost 는 None (pricing 미인식 — graceful)
    assert sess.cost_usd is None
    assert sess.cost_by_model_usd == {}
    assert sess.pricing_version is None


def test_parse_session_without_usage_field(tmp_path: Path) -> None:
    """assistant message 에 usage 부재 — 기존 동작 유지 (cost 차원 모두 default)."""
    p = tmp_path / "no_usage.jsonl"
    _write_jsonl(
        p,
        [
            {"sessionId": "N1", "timestamp": "2026-05-27T00:00:00Z"},
            # usage 없는 assistant message (기존 jsonl 호환)
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Bash"}]},
            },
        ],
    )
    sess = parse_session(p)
    assert sess is not None
    assert sess.tool_call_count == 1  # 기존 동작 유지
    assert sess.cost_usd is None
    assert sess.tokens_in == 0
    assert sess.cost_by_model_usd == {}
    assert sess.pricing_version is None


def test_session_to_dict_includes_cost_fields() -> None:
    """to_dict() 가 cost 차원 모두 포함 — MCP 응답 호환."""
    s = Session(
        session_id="X",
        source_path=Path("/tmp/x.jsonl"),
        cost_usd=1.23,
        tokens_in=10,
        tokens_out=20,
        tokens_cache_write_5m=30,
        tokens_cache_write_1h=40,
        tokens_cache_read=50,
        cost_by_model_usd={"claude-opus-4-7": 1.23},
        pricing_version=1,
    )
    d = s.to_dict()
    assert d["cost_usd"] == 1.23
    assert d["tokens_in"] == 10
    assert d["tokens_out"] == 20
    assert d["tokens_cache_write_5m"] == 30
    assert d["tokens_cache_write_1h"] == 40
    assert d["tokens_cache_read"] == 50
    assert d["cost_by_model_usd"] == {"claude-opus-4-7": 1.23}
    assert d["pricing_version"] == 1


def test_aggregate_sessions_sums_cost_across_sessions() -> None:
    """aggregate 가 cost_usd / cost_by_model_usd / pricing_versions_seen 합산."""
    s1 = Session(
        session_id="S1",
        source_path=Path("/tmp/s1.jsonl"),
        cost_usd=2.0,
        tokens_in=100,
        cost_by_model_usd={"claude-opus-4-7": 2.0},
        pricing_version=1,
    )
    s2 = Session(
        session_id="S2",
        source_path=Path("/tmp/s2.jsonl"),
        cost_usd=3.0,
        tokens_in=200,
        cost_by_model_usd={
            "claude-opus-4-7": 1.0,
            "claude-sonnet-4-6": 2.0,
        },
        pricing_version=1,
    )
    s3 = Session(
        session_id="S3",
        source_path=Path("/tmp/s3.jsonl"),
        # cost_usd=None — 미인식 모델 case
    )
    agg = aggregate_sessions([s1, s2, s3])
    assert agg["total_cost_usd"] == pytest.approx(5.0, rel=1e-9)
    assert agg["cost_by_model_usd"] == {
        "claude-opus-4-7": pytest.approx(3.0, rel=1e-9),
        "claude-sonnet-4-6": pytest.approx(2.0, rel=1e-9),
    }
    assert agg["pricing_versions_seen"] == [1]


def test_aggregate_sessions_no_cost_returns_none() -> None:
    """모든 session 이 cost 없음 — total_cost_usd None, breakdown empty."""
    s = Session(session_id="S", source_path=Path("/tmp/s.jsonl"))
    agg = aggregate_sessions([s])
    assert agg["total_cost_usd"] is None
    assert agg["cost_by_model_usd"] == {}
    assert agg["pricing_versions_seen"] == []
