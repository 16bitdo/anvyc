"""Anthropic cost adapter — (i) session jsonl channel (CP-13 PR-13B1).

PR-13A 의 `activity.collect_sessions()` 결과를 profile 별 / period 별 그룹화
후 `CostReport` (schema v1) 으로 변환. (ii) admin API channel 은 v0.2 별도
ADR 로 deferred (ADR v1.2 §2.3 / §4.2.3 / §5).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from anvyc.core import activity
from anvyc.core.cost.ledger import (
    Account,
    BreakdownItem,
    CostReport,
    CostReportMeta,
    Period,
)

SOURCE = "anthropic"
PROFILE_DEFAULT = "default"
CLAUDE_HOME_PREFIX = ".claude"


def _session_profile(path: Path, home: Path) -> str | None:
    """session source_path 에서 profile 명 추출.

    `~/.claude/...` → `'default'`, `~/.claude-edward/...` → `'edward'`. home
    외부 경로면 `None` (graceful — 분류 실패는 합산에서 제외).
    """
    try:
        relative = path.resolve().relative_to(home)
    except (ValueError, OSError):
        return None
    if not relative.parts:
        return None
    first = relative.parts[0]
    if first == CLAUDE_HOME_PREFIX:
        return PROFILE_DEFAULT
    prefix_dash = f"{CLAUDE_HOME_PREFIX}-"
    if first.startswith(prefix_dash):
        return first[len(prefix_dash):]
    return None


def _in_period(session: activity.Session, period: Period) -> bool:
    """session.started_at 가 period 내 (started_at 기준 단일 catalog).

    naive datetime 은 UTC 로 간주 (jsonl 의 timestamp 가 항상 UTC ISO).
    """
    ts = session.started_at
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return period.start <= ts < period.end


class AnthropicAdapter:
    """Anthropic (i) session jsonl channel adapter.

    `discover_accounts()` = `~/.claude*` 의 모든 profile.
    `fetch_period()` = profile + period filter 후 PR-13A 의 cost_usd /
    cost_by_model_usd 합산. (ii) admin API channel 은 v0.2 deferred —
    `supports_realtime()=True` 이지만 reconciliation 자동화는 미구현 (수동
    console 비교).
    """

    name = SOURCE
    optional_dep_group: str | None = None  # core dep only (pyyaml + jsonl)

    def __init__(self, home: Path | None = None) -> None:
        self._home = home or Path.home()

    def discover_accounts(self) -> Iterator[Account]:
        """`~/.claude*` glob 에서 profile 추출."""
        seen: set[str] = set()
        for root in activity.discover_session_roots(self._home):
            # root = ~/.claude*/projects → root.parent = ~/.claude*
            profile_part = root.parent.name
            if profile_part == CLAUDE_HOME_PREFIX:
                profile = PROFILE_DEFAULT
            elif profile_part.startswith(f"{CLAUDE_HOME_PREFIX}-"):
                profile = profile_part[len(CLAUDE_HOME_PREFIX) + 1:]
            else:
                continue
            if profile in seen:
                continue
            seen.add(profile)
            yield Account(source=SOURCE, key=profile)

    def fetch_period(self, account: Account, period: Period) -> CostReport:
        """account / period filter 후 cost 합산.

        session.started_at 가 period 안에 있는 경우만 포함. `cost_usd is None`
        세션 (pricing 미인식) 은 token 만 가질 뿐 합산 제외 — PR-13A 의
        graceful 정책 일관.
        """
        if account.source != SOURCE:
            raise ValueError(
                f"AnthropicAdapter.fetch_period: account.source != "
                f"{SOURCE!r} (got {account.source!r})"
            )
        # home override 가 fake_home 등 test fixture 를 따라가도록 roots 명시.
        # roots 명시 경로 = activity.collect_sessions 의 legacy path —
        # iter_session_files(roots) → parse_session 직접 호출.
        roots = activity.discover_session_roots(self._home)
        sessions = activity.collect_sessions(roots=roots)
        scoped = [
            s
            for s in sessions
            if _session_profile(s.source_path, self._home) == account.key
            and _in_period(s, period)
        ]

        total = 0.0
        by_model: dict[str, float] = {}
        versions: set[int] = set()
        for s in scoped:
            if s.cost_usd is not None:
                total += s.cost_usd
            for m, c in s.cost_by_model_usd.items():
                by_model[m] = by_model.get(m, 0.0) + c
            if s.pricing_version is not None:
                versions.add(s.pricing_version)

        breakdown = [
            BreakdownItem(dim="model", key=m, amount=round(amt, 6))
            for m, amt in sorted(by_model.items(), key=lambda kv: -kv[1])
        ]
        pricing_version = max(versions) if versions else None

        return CostReport(
            source=SOURCE,
            account=account.key,
            period=period,
            amount=round(total, 6),
            currency="USD",
            breakdown=breakdown,
            collected_at=datetime.now(UTC),
            meta=CostReportMeta(
                pricing_version=pricing_version,
                extra={"session_count": len(scoped)},
            ),
        )

    def supports_realtime(self) -> bool:
        return True


__all__ = ["AnthropicAdapter", "SOURCE"]
