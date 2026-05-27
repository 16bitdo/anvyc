"""Cost API — CLI + MCP 공통 호출 helper (CP-13 PR-13B1).

`anvyc cost {collect, summary}` CLI 와 MCP `cost_summary` tool 이 본 모듈의
함수를 호출. period 해석 / adapter dispatch / 캐시 read 의 단일 진입점.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
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
    include_krw: bool = True,
) -> dict[str, Any]:
    """MCP `cost_summary` / CLI `cost summary` 의 단일 진입점.

    `refresh=True` 시 어댑터 직접 호출 (캐시 갱신), 기본은 캐시 우선 + 부재 시
    어댑터 호출 fallback.

    `include_krw=True` (default) 시 fx 가용하면 KRW 추가 (PR-13B2). fx 실패 시
    USD only — graceful (`total_amount_krw = None`).
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

    # PR-13B2: KRW 추가 (fx 가용 시 — fx fetch 실패 / cache 14d 이상 stale 시
    # graceful None 으로 fallback).
    if include_krw:
        from anvyc.core.cost.fx import try_get_usd_to_krw_rate

        fx_rate = try_get_usd_to_krw_rate(cache_root=cache_root)
        if fx_rate is not None:
            summary["total_amount_krw"] = round(
                summary["total_amount_usd"] * fx_rate.rate, 2
            )
            summary["fx_rate_basis"] = fx_rate.basis_string()
            summary["fx_stale"] = fx_rate.is_stale
        else:
            summary["total_amount_krw"] = None
            summary["fx_rate_basis"] = None
            summary["fx_stale"] = None

    # PR-13E2: budget_evaluations 추가 (PR-13B2 의 budgets.py 활용).
    # ccinspector scheduler 의 health-status.py 가 본 응답을 read 해서
    # cost-budget-exceeded severity 매핑. budgets.yml 부재 시 [] (graceful).
    summary["budget_evaluations"] = _build_budget_evaluations(reports)
    return summary


def _build_budget_evaluations(
    reports: list[CostReport],
) -> list[dict[str, Any]]:
    """`~/.config/anvyc/cost/budgets.yml` load + (source, account) 별 합산
    → 각 budget evaluate → JSON-serializable dict list.

    부재 / 빈 budgets / 매칭 0 — 모두 graceful (`[]`).
    """
    from anvyc.core.cost.budgets import evaluate as evaluate_budgets
    from anvyc.core.cost.budgets import load_budgets

    try:
        budgets = load_budgets()
    except Exception:
        return []
    if not budgets:
        return []

    actuals: dict[tuple[str, str], float] = {}
    for r in reports:
        key = (r.source, r.account)
        actuals[key] = actuals.get(key, 0.0) + r.amount

    evaluations = evaluate_budgets(actuals, budgets)
    return [
        {
            "source": e.budget.source,
            "account": e.budget.account,
            "period": e.budget.period,
            "amount_usd_limit": e.budget.amount_usd,
            "actual_usd": e.actual_usd,
            "usage_pct": e.usage_pct,
            "severity": e.severity.value,
        }
        for e in evaluations
    ]


def _format_summary_text(summary: dict[str, Any]) -> str:
    """터미널 친화 텍스트 (CLI default — JSON 안 줄 때)."""
    lines = []
    p = summary.get("period", {})
    lines.append(
        f"period: {p.get('start', '?')} → {p.get('end', '?')}  ({summary['currency']})"
    )
    # PR-13B2: KRW 라인 (fx 가용 시).
    krw = summary.get("total_amount_krw")
    if krw is not None:
        stale = "~" if summary.get("fx_stale") else ""
        basis = summary.get("fx_rate_basis", "")
        lines.append(
            f"total:  ${summary['total_amount_usd']:.4f}"
            f"  ≈  {stale}₩{krw:,.0f}  (fx: {basis})"
        )
    else:
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
    # PR-13E2: budgets (있을 때만 표시). 색상 prefix 는 ccinspector statusline
    # 에서 처리 — 본 CLI 는 평문.
    evals = summary.get("budget_evaluations", [])
    if evals:
        lines.append("budgets:")
        for e in evals:
            lines.append(
                f"  {e['source']}:{e['account']:10s} "
                f"${e['actual_usd']:.2f} / ${e['amount_usd_limit']:.2f} "
                f"({e['usage_pct']:.1f}% {e['severity']})"
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


# PR-13B2: retention / ledger helpers ----------------------------------------


def gc_raw_daily(
    keep_days: int = 90,
    *,
    cache_root: Path | None = None,
    dry_run: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    """raw daily cache 의 `keep_days` 이전 파일 정리 (DESIGN §38.5).

    cache 파일명이 `YYYY-MM-DD.json` 형식 — 그 외 (fx/*.json 등 future) 는 skip.
    `dry_run=True` 시 삭제하지 않고 list 만 반환.
    """
    today_actual = today or datetime.now(UTC).date()
    cutoff = today_actual - timedelta(days=keep_days)
    removed: list[Path] = []
    kept: list[Path] = []
    for path in iter_cache_files(root=cache_root):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            kept.append(path)
            continue
        if day < cutoff:
            removed.append(path)
            if not dry_run:
                path.unlink(missing_ok=True)
        else:
            kept.append(path)
    return {
        "today": today_actual.isoformat(),
        "cutoff": cutoff.isoformat(),
        "keep_days": keep_days,
        "removed_count": len(removed),
        "kept_count": len(kept),
        "removed_paths": [str(p) for p in removed],
        "dry_run": dry_run,
    }


def ledger_rows(
    *,
    period: Period | None = None,
    source: str | None = None,
    account: str | None = None,
    cache_root: Path | None = None,
    include_meta: bool = False,
) -> list[dict[str, Any]]:
    """`anvyc cost ledger` 의 row 자료원 — period 의 cache rows.

    `include_meta=True` 시 measurement_cost_usd / org_id / collected_at 추가.
    """
    rows: list[dict[str, Any]] = []
    for path in iter_cache_files(
        source=source, account=account, root=cache_root
    ):
        r = read_cache(path)
        if r is None:
            continue
        if period is not None and not _period_intersects(r.period, period):
            continue
        row: dict[str, Any] = {
            "cache_date": path.stem,
            "source": r.source,
            "account": r.account,
            "period_start": r.period.start.isoformat(),
            "period_end": r.period.end.isoformat(),
            "amount_usd": round(r.amount, 6),
            "model_breakdown_count": sum(
                1 for b in r.breakdown if b.dim == "model"
            ),
            "pricing_version": r.meta.pricing_version,
        }
        if include_meta:
            row["measurement_cost_usd"] = r.meta.measurement_cost_usd
            row["org_id"] = r.meta.org_id
            row["collected_at"] = (
                r.collected_at.isoformat() if r.collected_at else None
            )
        rows.append(row)
    return rows


__all__ = [
    "InvalidPeriodSpecError",
    "UnknownSourceError",
    "collect_and_persist",
    "collect_reports",
    "gc_raw_daily",
    "ledger_rows",
    "read_cached_reports",
    "resolve_period",
    "summarize_reports",
    "summary_json",
    "summary_payload",
    "summary_text",
]
