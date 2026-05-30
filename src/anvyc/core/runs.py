"""run-record (CP-14 anvyx) reader + 집계 — L4 실행 엔진 원장 흡수.

anvyx (L4) 가 `~/.config/anvyx/runs/<YYYY-MM-DD>.jsonl` 에 emit 한 C5 run-record 를
anvyc (L2) 가 읽어 집계한다 (CP-8 emit→aggregate→display 패턴). read-only.

스키마 SoT: role-based-ruleset/metadata/run-record-schema.yaml (schema_version:1).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RUNS_DIR_DEFAULT = Path.home() / ".config" / "anvyx" / "runs"
RUN_FILE_GLOB = "*.jsonl"


@dataclass
class Run:
    """단일 run-record 의 정규화된 뷰 (집계/표시에 필요한 필드)."""

    run_id: str
    status: str
    agent: str | None
    model: str | None
    cwd: str | None
    started_at: str | None
    stopped_at: str | None
    duration_s: float | None
    exit_reason: str | None
    exit_code: int | None
    tool_calls: int
    cost_usd: float
    tokens_total: int
    machine_id: str | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "agent": self.agent,
            "model": self.model,
            "cwd": self.cwd,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "duration_s": self.duration_s,
            "exit_reason": self.exit_reason,
            "exit_code": self.exit_code,
            "tool_calls": self.tool_calls,
            "cost_usd": self.cost_usd,
            "tokens_total": self.tokens_total,
            "machine_id": self.machine_id,
            "error": self.error,
        }


def discover_run_files(runs_dir: Path | None = None) -> list[Path]:
    """run-record jsonl 파일 목록 (날짜순 정렬)."""
    base = runs_dir or RUNS_DIR_DEFAULT
    if not base.is_dir():
        return []
    return sorted(base.glob(RUN_FILE_GLOB))


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _parse_run(obj: dict[str, Any]) -> Run | None:
    """run-record dict → Run. run_id 없으면 None (스킵)."""
    run_id = obj.get("run_id")
    if not isinstance(run_id, str):
        return None

    tokens_total = 0
    tokens = obj.get("tokens")
    if isinstance(tokens, dict):
        for val in tokens.values():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                tokens_total += int(val)

    cost = obj.get("cost_usd")
    cost_usd = float(cost) if isinstance(cost, (int, float)) else 0.0

    duration = obj.get("duration_s")
    duration_s = float(duration) if isinstance(duration, (int, float)) else None

    tool_calls = obj.get("tool_calls")
    tool_calls_int = tool_calls if isinstance(tool_calls, int) else 0

    exit_code = obj.get("exit_code")
    exit_code_int = exit_code if isinstance(exit_code, int) else None

    status = obj.get("status")
    return Run(
        run_id=run_id,
        status=status if isinstance(status, str) else "unknown",
        agent=_opt_str(obj.get("agent")),
        model=_opt_str(obj.get("model")),
        cwd=_opt_str(obj.get("cwd")),
        started_at=_opt_str(obj.get("started_at")),
        stopped_at=_opt_str(obj.get("stopped_at")),
        duration_s=duration_s,
        exit_reason=_opt_str(obj.get("exit_reason")),
        exit_code=exit_code_int,
        tool_calls=tool_calls_int,
        cost_usd=cost_usd,
        tokens_total=tokens_total,
        machine_id=_opt_str(obj.get("machine_id")),
        error=_opt_str(obj.get("error")),
    )


def iter_runs(
    runs_dir: Path | None = None, *, agent: str | None = None
) -> Iterator[Run]:
    """모든 run-record 를 yield (손상 라인/파일은 skip). agent 필터 옵션."""
    for path in discover_run_files(runs_dir):
        try:
            with path.open(encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    run = _parse_run(obj)
                    if run is None:
                        continue
                    if agent is not None and run.agent != agent:
                        continue
                    yield run
        except OSError:
            continue


def collect_runs(
    runs_dir: Path | None = None, *, agent: str | None = None
) -> list[Run]:
    """run-record 전체를 started_at 오름차순으로 정렬해 반환."""
    runs = list(iter_runs(runs_dir, agent=agent))
    runs.sort(key=lambda r: r.started_at or "")
    return runs


def aggregate_runs(runs: list[Run]) -> dict[str, Any]:
    """run list 의 통합 통계 — `run_summary` MCP tool / `runs summary` CLI payload."""
    by_status: Counter[str] = Counter(r.status for r in runs)
    by_exit: Counter[str] = Counter(
        r.exit_reason for r in runs if r.exit_reason is not None
    )
    by_agent: Counter[str] = Counter(
        r.agent for r in runs if r.agent is not None
    )
    starts = [r.started_at for r in runs if r.started_at]
    return {
        "total_runs": len(runs),
        "by_status": dict(by_status),
        "by_exit_reason": dict(by_exit),
        "by_agent": dict(by_agent),
        "total_cost_usd": round(sum(r.cost_usd for r in runs), 6),
        "total_tokens": sum(r.tokens_total for r in runs),
        "total_tool_calls": sum(r.tool_calls for r in runs),
        "oldest_run_started_at": min(starts) if starts else None,
        "newest_run_started_at": max(starts) if starts else None,
    }
