"""mcp-extra-importable check.

`anvyc serve --mcp` 는 anvyc 가 설치된 환경에 `mcp` Python 패키지 (extra
`[mcp]`) 가 함께 깔려 있어야 동작한다. dev wrapper 환경에서 venv 의 mcp
extra 가 누락되면 Claude Code / Cursor 의 mcp.json 연결이 silent 하게
`Failed to connect` 로 떨어진다 — 사용자가 추적하기 어려운 실패 경로라
doctor 에서 1초 만에 감지하도록 한다.

read-only 원칙: 자동 install 하지 않고 WARNING + 설치 명령만 제시.
"""
from __future__ import annotations

import importlib.util

from anvyc.checks.base import CheckContext, CheckResult, Severity


class McpExtraImportableCheck:
    name = "mcp-extra-importable"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        if importlib.util.find_spec("mcp") is not None:
            return []
        return [
            CheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                message=(
                    "`mcp` 패키지가 현재 Python 환경에 설치되어 있지 않습니다 — "
                    "`anvyc serve --mcp` 가 동작하지 않아 Claude Code / Cursor 의 "
                    "MCP 연결이 실패합니다."
                ),
                suggestion=(
                    "PyPI 설치: pip install 'anvyc[mcp]' (또는 uv tool install 'anvyc[mcp]'). "
                    "dev 환경: bash scripts/dev-install.sh (ANVYC_EXTRAS 기본값이 dev,mcp)."
                ),
            )
        ]
