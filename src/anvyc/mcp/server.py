"""anvyc MCP server (P6, v0.9.0).

stdio transport — Claude Code / Cursor 의 mcp.json 에서:

  {"mcpServers": {"anvyc": {"command": "anvyc", "args": ["serve", "--mcp"]}}}

8 read-only tool 노출 (D21 + CP-1 3/3 + CP-13):
  project_show       cwd 의 단일 project connection
  project_list       root 아래 모든 project matrix
  project_doctor     cwd 의 정합성 14 check
  doctor             anvyc 환경 진단 (24 check)
  tools_list         10 도구 메타데이터 + 상태 (label/category/summary/...)
  activity_summary   Claude Code session 통합 통계 (CP-1)
  tool_call_stats    tool 별 사용 카운트 ranking (CP-1)
  cost_summary       period 별 source / account 합산 (CP-13)

write 영역 (backup/apply/restore) 은 의도적 미포함 — agent 가 destructive
실행 못 함. 사용자가 CLI 로 명시 실행.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
except ImportError as e:  # pragma: no cover - import-time error path
    raise SystemExit(
        "anvyc MCP server requires the [mcp] extra. "
        "Install: pip install 'anvyc[mcp]' or uv tool install 'anvyc[mcp]'"
    ) from e


server: Server = Server("anvyc")


# ---------- tool definitions ------------------------------------------------


def _tool_defs() -> list[Tool]:
    return [
        Tool(
            name="project_show",
            description=(
                "cwd (또는 명시 path) 의 단일 project connection 정보 "
                "(AWS profile / GitHub remote / Pulumi project / dev_env "
                "/ tool_versions). DESIGN §32 schema."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "project root (default: cwd).",
                    },
                    "reveal_secrets": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "dev_env 의 secret 패턴 매칭 값을 raw 노출 (default: ***REDACTED***)."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="project_list",
            description=(
                "입력 root 아래 모든 project 의 connection matrix. "
                "각 entry 는 project_show 와 동일 schema. DESIGN §33.1."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "roots": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "scan roots (미지정 시 anvyc.yaml project_roots 또는 표준 루트).",
                    },
                    "reveal_secrets": {
                        "type": "boolean",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="project_doctor",
            description=(
                "cwd (또는 명시 path) 의 connection 정합성 14 check "
                "(gh/커밋 신원 실체 대조 포함). DESIGN §33.2/§33.3."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "project root (default: cwd).",
                    },
                },
            },
        ),
        Tool(
            name="doctor",
            description=(
                "anvyc 환경 진단 (global, 24 check). "
                "cross-user / venv-hidden / op-references / sops / mcp-tokens / "
                "project-aws-profile-mapping / aws-profile-status / "
                "multi-account-detected / unused-aws-profiles / creds-expiry / "
                "cost-aws-explorer-iam / cost-github-pat-scope / "
                "hook-integrity-risk-gate / work-cwd-track-wired 등."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "only": {"type": "array", "items": {"type": "string"}},
                    "skip": {"type": "array", "items": {"type": "string"}},
                },
            },
        ),
        Tool(
            name="tools_list",
            description=(
                "anvyc 가 관리하는 10 도구의 메타데이터 + 런타임 상태 "
                "(tool / label / category / summary / enabled / detected / files / "
                "secrets / includes / excludes / default_enabled / config_kind / since). "
                "shell / git / aws / gh / cursor / claude / iterm2 / pulumi "
                "/ dev_env / shell_prompt."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="activity_summary",
            description=(
                "AI agent session 의 통합 통계 (CP-1 + CP-7 멀티 에이전트). "
                "기본은 모든 등록 agent union — 현재 Claude Code "
                "(~/.claude*/projects/*/*.jsonl) 만 impl, Cursor/Codex 는 stub 으로 "
                "silent skip. `agent` 명시 시 단일 dispatch — stub 명시는 error. "
                "반환: total_sessions / total_events / total_tool_calls / "
                "total_duration_seconds / oldest~newest range / tools_used dict."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "description": (
                            "단일 agent 명 (claude_code / cursor / codex). 미지정 "
                            "시 모든 등록 agent 통합. CP-7 의 멀티 에이전트 dispatch."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="tool_call_stats",
            description=(
                "tool 별 사용 카운트 ranking (CP-1 + CP-7) + risk-gate 차단 통계 "
                "(CP-8 + CP-11 PR-11E). 반환 dict 형식: "
                "{tool_call_ranking: [{name, count}, ...], blocked: "
                "{total_blocks, by_hook, by_agent, oldest_block_at, "
                "newest_block_at}}. `top` N 으로 ranking 상위 N 개만 반환. "
                "`agent` 명시 시 ranking + blocked 둘 다 그 agent 의 데이터만 "
                "필터 — audit jsonl 의 'agent' 필드와 정확히 일치하는 event 만."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "top": {
                        "type": "integer",
                        "description": "ranking 상위 N 개 반환 (미지정 시 전체).",
                    },
                    "agent": {
                        "type": "string",
                        "description": (
                            "단일 agent 명 (claude_code / cursor / codex). 미지정 "
                            "시 모든 등록 agent 통합. ranking + blocked 통계 둘 "
                            "다 영향 (CP-11 PR-11E)."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="cost_summary",
            description=(
                "CP-13 cost observability — period 별 source / account 합산 "
                "(anthropic: session jsonl channel — admin API channel 은 "
                "v0.2 deferred; aws/github: cost-aws/cost-github extra). 반환: "
                "{total_amount_usd, currency, by_source, by_account, by_model, "
                "pricing_versions_seen, period, report_count}."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": (
                            "source 필터: anthropic | aws | github. 미지정 시 "
                            "모든 등록 어댑터."
                        ),
                    },
                    "period": {
                        "type": "string",
                        "description": "mtd | YYYY-MM (default: mtd).",
                    },
                    "refresh": {
                        "type": "boolean",
                        "description": (
                            "true 시 어댑터 직접 호출 + 캐시 갱신. false "
                            "(default) 시 캐시 우선 (비어있으면 fallback collect)."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="run_summary",
            description=(
                "CP-14 L4 실행 엔진 원장 — anvyx (~/.config/anvyx/runs/*.jsonl) 의 "
                "run-record 통합 통계 (총 run 수 / status·exit_reason·agent 별 분포 / "
                "총 비용·토큰·tool call). read-only — anvyx 가 emit, anvyc 가 집계 "
                "(CP-8 패턴). anvyx 미설치/run 부재 시 total_runs=0."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "description": "agent 필터 (claude_code 등). 미지정 시 전체.",
                    },
                    "repo": {
                        "type": "string",
                        "description": "repo(owner/name) scope 필터. 미지정 시 전체. (CP-16)",
                    },
                },
            },
        ),
    ]


@server.list_tools()  # type: ignore
async def list_tools() -> list[Tool]:  # pragma: no cover - thin wrapper
    return _tool_defs()


# ---------- dispatch --------------------------------------------------------


def _dispatch(name: str, arguments: dict[str, Any]) -> Any:
    """sync core function 호출 (async wrapper 가 이 함수만 호출).

    각 tool 의 결과는 JSON-serializable dict / list. raw secret 은 D11c
    redaction default 적용 (`reveal_secrets=True` 명시 시만 raw).
    """
    args = arguments or {}

    if name == "project_show":
        from anvyc.core.project_info import collect_project_info, to_dict

        p = Path(args.get("path") or ".")
        info = collect_project_info(p, redact_secrets=not args.get("reveal_secrets", False))
        return to_dict(info)

    if name == "project_list":
        from anvyc.core.project_discovery import PROJECT_MARKERS, discover_projects
        from anvyc.core.project_info import collect_project_info, to_dict
        from anvyc.core.project_scope import iter_project_dirs

        explicit = args.get("roots")
        if explicit:
            projs = discover_projects(list(explicit))  # 명시 override
        else:
            projs = iter_project_dirs(markers=PROJECT_MARKERS, max_depth=2)
        reveal = bool(args.get("reveal_secrets", False))
        return [to_dict(collect_project_info(p, redact_secrets=not reveal)) for p in projs]

    if name == "project_doctor":
        from anvyc.core.project_doctor import run_project_doctor

        p = Path(args.get("path") or ".")
        report = run_project_doctor(p)
        return report.to_payload()

    if name == "doctor":
        from anvyc.core.doctor import run_doctor

        only = args.get("only") or None
        skip = args.get("skip") or None
        doctor_report = run_doctor(only=only, skip=skip)
        return {"results": [r.to_dict() for r in doctor_report.results]}

    if name == "tools_list":
        from anvyc.cli import _collect_tools_rows

        return _collect_tools_rows(None)

    if name == "activity_summary":
        from anvyc.core.activity import aggregate_sessions, collect_sessions

        agent = args.get("agent") if isinstance(args.get("agent"), str) else None
        return aggregate_sessions(collect_sessions(agent=agent))

    if name == "tool_call_stats":
        from anvyc.core.activity import collect_sessions, tool_call_ranking
        from anvyc.core.audit_log import aggregate_block_events, collect_block_events

        top = args.get("top")
        agent = args.get("agent") if isinstance(args.get("agent"), str) else None
        ranking = tool_call_ranking(
            collect_sessions(agent=agent),
            top=top if isinstance(top, int) else None,
        )
        # CP-11 PR-11E: agent 명시 시 blocked 통계도 그 agent 의 audit 만 필터.
        blocked = aggregate_block_events(collect_block_events(agent=agent))
        return {"tool_call_ranking": ranking, "blocked": blocked}

    if name == "cost_summary":
        from anvyc.core.cost.api import summary_payload

        source_raw = args.get("source")
        source = source_raw if isinstance(source_raw, str) else None
        period_raw = args.get("period")
        period_spec = period_raw if isinstance(period_raw, str) else "mtd"
        refresh = bool(args.get("refresh", False))
        return summary_payload(
            source=source, period_spec=period_spec, refresh=refresh
        )

    if name == "run_summary":
        from anvyc.core.runs import aggregate_runs, collect_runs

        agent = args.get("agent") if isinstance(args.get("agent"), str) else None
        repo = args.get("repo") if isinstance(args.get("repo"), str) else None
        return aggregate_runs(collect_runs(agent=agent, repo=repo))

    raise ValueError(f"unknown tool: {name}")


@server.call_tool()  # type: ignore
async def call_tool(  # pragma: no cover - thin wrapper
    name: str, arguments: dict[str, Any]
) -> list[TextContent]:
    try:
        result = _dispatch(name, arguments or {})
        return [
            TextContent(
                type="text",
                text=_json.dumps(result, ensure_ascii=False, indent=2),
            )
        ]
    except Exception as exc:
        return [
            TextContent(
                type="text",
                text=_json.dumps({"error": str(exc)}, ensure_ascii=False),
            )
        ]


# ---------- entrypoint ------------------------------------------------------


async def _main() -> None:  # pragma: no cover - I/O loop
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run() -> None:
    """sync entrypoint — `anvyc serve --mcp` 가 호출."""
    import asyncio

    asyncio.run(_main())
