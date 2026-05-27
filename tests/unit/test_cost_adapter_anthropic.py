"""Unit tests for anvyc.core.cost.adapters.anthropic (CP-13 PR-13B1)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from anvyc.core.cost.adapters.anthropic import (
    SOURCE,
    AnthropicAdapter,
    _session_profile,
)
from anvyc.core.cost.ledger import Account, Period


def _write_jsonl(path: Path, events: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


def _assistant_event(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    timestamp: str = "2026-05-15T00:00:00Z",
) -> dict[str, object]:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": 0,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 0,
                    "ephemeral_1h_input_tokens": 0,
                },
            },
            "content": [],
        },
    }


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    """3 profile 합성: .claude / .claude-edward / .claude-jklee."""
    home = tmp_path / "home"
    # default profile
    _write_jsonl(
        home / ".claude" / "projects" / "proj-a" / "S1.jsonl",
        [
            {
                "sessionId": "S1",
                "cwd": "/tmp",
                "timestamp": "2026-05-15T00:00:00Z",
            },
            _assistant_event(
                "claude-opus-4-7",
                input_tokens=1_000_000,
                output_tokens=0,
                timestamp="2026-05-15T00:00:00Z",
            ),  # = $5
        ],
    )
    # edward profile
    _write_jsonl(
        home / ".claude-edward" / "projects" / "proj-b" / "S2.jsonl",
        [
            {
                "sessionId": "S2",
                "cwd": "/tmp",
                "timestamp": "2026-05-15T00:00:00Z",
            },
            _assistant_event(
                "claude-sonnet-4-6",
                input_tokens=1_000_000,
                output_tokens=0,
                timestamp="2026-05-15T00:00:00Z",
            ),  # = $3
        ],
    )
    # jklee profile — period 밖
    _write_jsonl(
        home / ".claude-jklee" / "projects" / "proj-c" / "S3.jsonl",
        [
            {
                "sessionId": "S3",
                "cwd": "/tmp",
                "timestamp": "2026-04-15T00:00:00Z",  # 4월 — May period 밖
            },
            _assistant_event(
                "claude-haiku-4-5",
                input_tokens=1_000_000,
                output_tokens=0,
                timestamp="2026-04-15T00:00:00Z",
            ),  # = $1 (April)
        ],
    )
    return home


def test_session_profile_extraction() -> None:
    home = Path("/Users/test")
    assert (
        _session_profile(
            home / ".claude" / "projects" / "p" / "s.jsonl", home
        )
        == "default"
    )
    assert (
        _session_profile(
            home / ".claude-edward" / "projects" / "p" / "s.jsonl", home
        )
        == "edward"
    )
    assert (
        _session_profile(
            home / ".claude-jklee" / "projects" / "p" / "s.jsonl", home
        )
        == "jklee"
    )


def test_session_profile_unknown_path() -> None:
    home = Path("/Users/test")
    # home 외부 — None
    assert (
        _session_profile(
            Path("/elsewhere/some.jsonl"), home
        )
        is None
    )


def test_discover_accounts(fake_home: Path) -> None:
    adapter = AnthropicAdapter(home=fake_home)
    accounts = sorted(adapter.discover_accounts(), key=lambda a: a.key)
    assert accounts == [
        Account(source=SOURCE, key="default"),
        Account(source=SOURCE, key="edward"),
        Account(source=SOURCE, key="jklee"),
    ]


def test_fetch_period_filters_by_profile_and_period(fake_home: Path) -> None:
    """May 2026 — default 만 $5, edward 만 $3, jklee 는 4월이라 0."""
    adapter = AnthropicAdapter(home=fake_home)
    may = Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )

    default_report = adapter.fetch_period(
        Account(source=SOURCE, key="default"), may
    )
    assert default_report.source == "anthropic"
    assert default_report.account == "default"
    assert default_report.amount == pytest.approx(5.0, rel=1e-6)
    assert default_report.currency == "USD"
    assert default_report.breakdown == [
        # 단일 모델만 사용 — breakdown 1 entry
        default_report.breakdown[0]
    ]
    assert default_report.breakdown[0].dim == "model"
    assert default_report.breakdown[0].key == "claude-opus-4-7"
    assert default_report.meta.pricing_version == 1
    assert default_report.meta.extra.get("session_count") == 1

    edward_report = adapter.fetch_period(
        Account(source=SOURCE, key="edward"), may
    )
    assert edward_report.amount == pytest.approx(3.0, rel=1e-6)
    assert edward_report.breakdown[0].key == "claude-sonnet-4-6"

    # jklee 의 session 은 4월 — May period 에서 제외
    jklee_report = adapter.fetch_period(
        Account(source=SOURCE, key="jklee"), may
    )
    assert jklee_report.amount == pytest.approx(0.0)
    assert jklee_report.breakdown == []
    assert jklee_report.meta.extra.get("session_count") == 0


def test_fetch_period_april_includes_jklee(fake_home: Path) -> None:
    """April 2026 — jklee 만 $1."""
    adapter = AnthropicAdapter(home=fake_home)
    april = Period(
        start=datetime(2026, 4, 1, tzinfo=UTC),
        end=datetime(2026, 5, 1, tzinfo=UTC),
    )
    r = adapter.fetch_period(Account(source=SOURCE, key="jklee"), april)
    assert r.amount == pytest.approx(1.0, rel=1e-6)
    assert r.breakdown[0].key == "claude-haiku-4-5"


def test_fetch_period_wrong_source_raises(fake_home: Path) -> None:
    adapter = AnthropicAdapter(home=fake_home)
    p = Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="account.source"):
        adapter.fetch_period(Account(source="aws", key="some"), p)


def test_supports_realtime() -> None:
    adapter = AnthropicAdapter()
    assert adapter.supports_realtime() is True


def test_optional_dep_group_is_none() -> None:
    """anvyc core dep (pyyaml) 만 — optional group 불필요."""
    adapter = AnthropicAdapter()
    assert adapter.optional_dep_group is None
