"""tui-extra-importable check.

`anvyc tools configure` 는 `[tui]` extra(textual) 가 있으면 체크박스 TUI 를, 없으면
번호 토글 메뉴를 쓴다 — 즉 textual 미설치는 *실패가 아니라 기능 강등*이다. 따라서
mcp-extra-importable 과 달리 이 check 는 INFO 로, 더 나은 UX 를 원하는 사용자에게
설치 경로만 안내한다.

read-only 원칙: 자동 install 하지 않고 설치 명령만 제시.
"""
from __future__ import annotations

import importlib.util

from anvyc.checks.base import CheckContext, CheckResult, Severity


class TuiExtraImportableCheck:
    name = "tui-extra-importable"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        if importlib.util.find_spec("textual") is not None:
            return []
        return [
            CheckResult(
                check_name=self.name,
                severity=Severity.INFO,
                message=(
                    "[tui] extra(textual) 미설치 — `anvyc tools configure` 가 체크박스 TUI "
                    "대신 번호 토글 메뉴로 동작합니다 (기능 동일, 강등 아님)."
                ),
                suggestion=(
                    "체크박스 TUI 사용: pip install 'anvyc[tui]' (또는 uv tool install 'anvyc[tui]'). "
                    "dev 환경: bash scripts/dev-install.sh (ANVYC_EXTRAS 기본값에 tui 포함)."
                ),
            )
        ]
