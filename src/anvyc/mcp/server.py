"""anvyc MCP server (P6, v0.9.0).

stdio transport — Claude Code / Cursor 의 mcp.json 에서:

  {"mcpServers": {"anvyc": {"command": "anvyc", "args": ["serve", "--mcp"]}}}

5 read-only tool 노출 (D21):
  project_show       cwd 의 단일 project connection
  project_list       root 아래 모든 project matrix
  project_doctor     cwd 의 정합성 5 check
  doctor             anvyc 환경 진단 (12 check)
  tools_list         9 도구 enabled / detect

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
                            "dev_env 의 secret 패턴 매칭 값을 raw 노출 "
                            "(default: ***REDACTED***)."
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
                        "description": "scan roots (default: ~/Documents).",
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
                "cwd (또는 명시 path) 의 connection 정합성 5 check. "
                "DESIGN §33.2/§33.3."
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
                "anvyc 환경 진단 (global, 12 check). "
                "cross-user / venv-hidden / op-references / sops / mcp-tokens / "
                "project-aws-profile-mapping / aws-profile-status / "
                "multi-account-detected / unused-aws-profiles 등."
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
                "anvyc 가 관리하는 9 도구의 enabled / detect / file-count. "
                "shell / git / aws / gh / cursor / claude / iterm2 / pulumi "
                "/ dev_env."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.list_tools()
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
        info = collect_project_info(
            p, redact_secrets=not args.get("reveal_secrets", False)
        )
        return to_dict(info)

    if name == "project_list":
        from anvyc.core.project_discovery import DEFAULT_ROOTS, discover_projects
        from anvyc.core.project_info import collect_project_info, to_dict

        roots = args.get("roots") or list(DEFAULT_ROOTS)
        projs = discover_projects(roots)
        reveal = bool(args.get("reveal_secrets", False))
        return [
            to_dict(collect_project_info(p, redact_secrets=not reveal))
            for p in projs
        ]

    if name == "project_doctor":
        from anvyc.core.project_doctor import run_project_doctor

        p = Path(args.get("path") or ".")
        report = run_project_doctor(p)
        return {
            "path": str(report.path),
            "results": [r.to_dict() for r in report.results],
        }

    if name == "doctor":
        from anvyc.core.doctor import run_doctor

        only = args.get("only") or None
        skip = args.get("skip") or None
        report = run_doctor(only=only, skip=skip)
        return {"results": [r.to_dict() for r in report.results]}

    if name == "tools_list":
        from anvyc.cli import _collect_tools_rows

        return _collect_tools_rows(None)

    raise ValueError(f"unknown tool: {name}")


@server.call_tool()
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
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def run() -> None:
    """sync entrypoint — `anvyc serve --mcp` 가 호출."""
    import asyncio

    asyncio.run(_main())
