"""Unit tests for anvyc.core.cost.cache (CP-13 PR-13B1)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from anvyc.core.cost.cache import (
    cache_path,
    iter_cache_files,
    read_cache,
    write_cache,
)
from anvyc.core.cost.ledger import (
    BreakdownItem,
    CostReport,
    CostReportMeta,
    Period,
)


def _sample_report(source: str = "anthropic", account: str = "default") -> CostReport:
    return CostReport(
        source=source,
        account=account,
        period=Period(
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        ),
        amount=42.0,
        breakdown=[BreakdownItem(dim="model", key="claude-opus-4-7", amount=42.0)],
        collected_at=datetime(2026, 5, 27, tzinfo=UTC),
        meta=CostReportMeta(pricing_version=1),
    )


def test_cache_path_layout(tmp_path: Path) -> None:
    p = cache_path("anthropic", "edward", date(2026, 5, 27), root=tmp_path)
    assert p == tmp_path / "anthropic" / "edward" / "2026-05-27.json"


def test_write_cache_atomic_creates_parents(tmp_path: Path) -> None:
    r = _sample_report()
    target = write_cache(r, day=date(2026, 5, 27), root=tmp_path)
    assert target.exists()
    assert target == tmp_path / "anthropic" / "default" / "2026-05-27.json"
    # tempfile 흔적 없음
    assert not list(target.parent.glob(".cost-*.json.tmp"))
    # JSON 본문 유효
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["amount"] == 42.0
    assert payload["schema_version"] == 1


def test_read_cache_roundtrip(tmp_path: Path) -> None:
    original = _sample_report()
    path = write_cache(original, day=date(2026, 5, 27), root=tmp_path)
    restored = read_cache(path)
    assert restored is not None
    assert restored.source == original.source
    assert restored.account == original.account
    assert restored.amount == original.amount
    assert restored.breakdown == original.breakdown
    assert restored.meta.pricing_version == 1


def test_read_cache_missing_returns_none(tmp_path: Path) -> None:
    assert read_cache(tmp_path / "nope.json") is None


def test_read_cache_invalid_json_returns_none(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not-json{{{", encoding="utf-8")
    assert read_cache(bad) is None


def test_read_cache_schema_mismatch_returns_none(tmp_path: Path) -> None:
    """필수 키 부재 → KeyError catch → None."""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"source": "anthropic"}), encoding="utf-8")
    assert read_cache(bad) is None


def test_iter_cache_files_empty(tmp_path: Path) -> None:
    assert list(iter_cache_files(root=tmp_path / "nonexist")) == []


def test_iter_cache_files_filters(tmp_path: Path) -> None:
    """source / account filter — 모든 조합 정확히."""
    write_cache(_sample_report("anthropic", "default"), day=date(2026, 5, 1), root=tmp_path)
    write_cache(_sample_report("anthropic", "default"), day=date(2026, 5, 2), root=tmp_path)
    write_cache(_sample_report("anthropic", "edward"), day=date(2026, 5, 1), root=tmp_path)

    all_files = list(iter_cache_files(root=tmp_path))
    assert len(all_files) == 3

    anth_only = list(iter_cache_files(source="anthropic", root=tmp_path))
    assert len(anth_only) == 3

    edward_only = list(
        iter_cache_files(source="anthropic", account="edward", root=tmp_path)
    )
    assert len(edward_only) == 1
    assert "edward" in str(edward_only[0])
