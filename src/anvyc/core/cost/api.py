"""Cost API — CLI + MCP 공통 호출 helper (CP-13 PR-13B1).

`anvyc cost {collect, summary}` CLI 와 MCP `cost_summary` tool 이 본 모듈의
함수를 호출. period 해석 / adapter dispatch / 캐시 read 의 단일 진입점.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from anvyc.core.cost.adapters import ADAPTER_REGISTRY
from anvyc.core.cost.cache import iter_cache_files, read_cache, write_cache
from anvyc.core.cost.ledger import CostReport, Period


class UnknownSourceError(ValueError):
    def __init__(self, source: str, known: list[str]) -> None:
        super().__init__(
            f"unknown cost source: {source!r} (known: {known!r})"
        )
        self.source = source
        self.known = known


class InvalidPeriodSpecError(ValueError):
    def __init__(self, spec: str) -> None:
        super().__init__(
            f"invalid period spec: {spec!r} (expected 'mtd' or 'YYYY-MM')"
        )
        self.spec = spec


def resolve_period(spec: str, *, now: datetime | None = None) -> Period:
    """period spec → Period.

    `mtd`        → 현재 KST 달의 UTC 변환 1일 0시 ~ now (R10: KST 사용자 / UTC store)
    `YYYY-MM`    → 해당 UTC 월 1일 ~ 다음 월 1일

    naive datetime 으로 `now` 전달 시 UTC 로 간주.
    """
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)

    if spec == "mtd":
        start = current.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return Period(start=start, end=current)

    if len(spec) == 7 and spec[4] == "-":
        try:
            year, month = int(spec[:4]), int(spec[5:7])
        except ValueError as e:
            raise InvalidPeriodSpecError(spec) from e
        if not (1 <= month <= 12):
            raise InvalidPeriodSpecError(spec)
        start = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            end = datetime(year, month + 1, 1, tzinfo=UTC)
        return Period(start=start, end=end)

    raise InvalidPeriodSpecError(spec)


def collect_reports(
    period: Period,
    *,
    source: str | None = None,
    home: Path | None = None,
) -> list[CostReport]:
    """등록된 어댑터 호출 → CostReport list 반환.

    `source` 미지정 시 모든 등록 어댑터. `home` 은 테스트 fixture 용 — None
    시 어댑터 기본 (`Path.home()`).
    """
    if source is not None and source not in ADAPTER_REGISTRY:
        raise UnknownSourceError(source, sorted(ADAPTER_REGISTRY.keys()))
    selected = (
        {source: ADAPTER_REGISTRY[source]}
        if source
        else ADAPTER_REGISTRY
    )

    reports: list[CostReport] = []
    for adapter in selected.values():
        # adapter 가 home override 를 지원하면 사용 (anthropic).
        if home is not None and hasattr(adapter, "_home"):
            adapter._home = home  # noqa: SLF001 — test fixture path
        for account in adapter.discover_accounts():
            reports.append(adapter.fetch_period(account, period))
    return reports


def collect_and_persist(
    period: Period,
    *,
    source: str | None = None,
    home: Path | None = None,
    cache_root: Path | None = None,
) -> list[CostReport]:
    """`collect_reports` + 결과 캐시 저장.

    저장 시점의 `period.end.date()` 를 캐시 파일 이름으로 사용 (일별 캐시).
    """
    reports = collect_reports(period, source=source, home=home)
    day = period.end.date()
    for report in reports:
        write_cache(report, day=day, root=cache_root)
    return reports


def summarize_reports(
    reports: list[CostReport],
) -> dict[str, Any]:
    """CostReport list 의 합산 + breakdown.

    출력 구조:
      total_amount_usd, currency, by_source, by_account, by_model,
      pricing_versions_seen, report_count
    """
    total = 0.0
    by_source: dict[str, float] = {}
    by_account: dict[str, float] = {}
    by_model: dict[str, float] = {}
    pricing_versions: set[int] = set()

    for r in reports:
        total += r.amount
        by_source[r.source] = by_source.get(r.source, 0.0) + r.amount
        acct_key = f"{r.source}:{r.account}"
        by_account[acct_key] = by_account.get(acct_key, 0.0) + r.amount
        for b in r.breakdown:
            if b.dim == "model":
                by_model[b.key] = by_model.get(b.key, 0.0) + b.amount
        if r.meta.pricing_version is not None:
            pricing_versions.add(r.meta.pricing_version)

    return {
        "total_amount_usd": round(total, 6),
        "currency": "USD",
        "by_source": {k: round(v, 6) for k, v in by_source.items()},
        "by_account": {k: round(v, 6) for k, v in by_account.items()},
        "by_model": {k: round(v, 6) for k, v in by_model.items()},
        "pricing_versions_seen": sorted(pricing_versions),
        "report_count": len(reports),
    }


def read_cached_reports(
    *,
    source: str | None = None,
    account: str | None = None,
    period: Period | None = None,
    cache_root: Path | None = None,
) -> list[CostReport]:
    """cache 의 모든 CostReport read, optional period intersection filter."""
    reports: list[CostReport] = []
    for path in iter_cache_files(source=source, account=account, root=cache_root):
        r = read_cache(path)
        if r is None:
            continue
        if period is not None and not _period_intersects(r.period, period):
            continue
        reports.append(r)
    return reports


def _period_intersects(a: Period, b: Period) -> bool:
    return a.start < b.end and b.start < a.end


def summary_payload(
    *,
    source: str | None = None,
    period_spec: str = "mtd",
    cache_root: Path | None = None,
    home: Path | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """MCP `cost_summary` / CLI `cost summary` 의 단일 진입점.

    `refresh=True` 시 어댑터 직접 호출 (캐시 갱신), 기본은 캐시 우선 + 부재 시
    어댑터 호출 fallback.
    """
    period = resolve_period(period_spec)
    if refresh:
        reports = collect_and_persist(
            period, source=source, home=home, cache_root=cache_root
        )
    else:
        reports = read_cached_reports(
            source=source, period=period, cache_root=cache_root
        )
        if not reports:
            # cache 비어있으면 first-run UX 위해 즉시 collect.
            reports = collect_and_persist(
                period, source=source, home=home, cache_root=cache_root
            )

    summary = summarize_reports(reports)
    summary["period"] = period.to_dict()
    summary["source_filter"] = source
    summary["refresh"] = refresh
    return summary


def _format_summary_text(summary: dict[str, Any]) -> str:
    """터미널 친화 텍스트 (CLI default — JSON 안 줄 때)."""
    lines = []
    p = summary.get("period", {})
    lines.append(
        f"period: {p.get('start', '?')} → {p.get('end', '?')}  ({summary['currency']})"
    )
    lines.append(f"total:  ${summary['total_amount_usd']:.4f}")
    if summary["by_source"]:
        lines.append("by source:")
        for k, v in summary["by_source"].items():
            lines.append(f"  {k:15s} ${v:.4f}")
    if summary["by_model"]:
        lines.append("by model:")
        for k, v in sorted(
            summary["by_model"].items(), key=lambda kv: -kv[1]
        ):
            lines.append(f"  {k:25s} ${v:.4f}")
    if summary["pricing_versions_seen"]:
        lines.append(
            f"pricing_versions_seen: {summary['pricing_versions_seen']}"
        )
    lines.append(f"reports: {summary['report_count']}")
    return "\n".join(lines)


def summary_text(
    *,
    source: str | None = None,
    period_spec: str = "mtd",
    cache_root: Path | None = None,
    home: Path | None = None,
    refresh: bool = False,
) -> str:
    """summary text 직접 반환 — CLI default 출력."""
    s = summary_payload(
        source=source,
        period_spec=period_spec,
        cache_root=cache_root,
        home=home,
        refresh=refresh,
    )
    return _format_summary_text(s)


def summary_json(
    *,
    source: str | None = None,
    period_spec: str = "mtd",
    cache_root: Path | None = None,
    home: Path | None = None,
    refresh: bool = False,
) -> str:
    """summary JSON 문자열 (CLI --json / MCP 응답)."""
    s = summary_payload(
        source=source,
        period_spec=period_spec,
        cache_root=cache_root,
        home=home,
        refresh=refresh,
    )
    return json.dumps(s, ensure_ascii=False, indent=2)


# timedelta import (linters 가 unused 라 안 보고 mtd 의 future 확장에서 사용 검토)
_KEEP_TIMEDELTA = timedelta  # noqa: F841

__all__ = [
    "InvalidPeriodSpecError",
    "UnknownSourceError",
    "collect_and_persist",
    "collect_reports",
    "read_cached_reports",
    "resolve_period",
    "summarize_reports",
    "summary_json",
    "summary_payload",
    "summary_text",
]
