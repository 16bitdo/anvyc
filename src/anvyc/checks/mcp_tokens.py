"""mcp-tokens-warn check.

MCP (Model Context Protocol) 설정 파일에 raw token 이 있으면 WARNING + op://
마이그레이션 권유. anvyc 의 read-only 원칙에 따라 자동 수정 X.

scanner 가 이미 같은 라인의 op:// signal 을 인식해 severity 강등 처리하므로,
이 check 는 "scanner 가 critical/high 로 본 mcp 항목" 만 골라 안내한다.
"""
from __future__ import annotations

from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.security.scanner import scan_file

# 알려진 MCP 설정 파일 — 확장 시 anvyc.yaml 노출 검토
DEFAULT_MCP_PATHS: tuple[str, ...] = (
    "~/.cursor/mcp.json",
    "~/.claude/settings.json",
    "~/.codex/settings.json",
)


class McpTokensWarnCheck:
    name = "mcp-tokens-warn"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        results: list[CheckResult] = []
        for path_str in DEFAULT_MCP_PATHS:
            p = Path(path_str).expanduser()
            if not p.is_file():
                continue
            findings = scan_file(p)
            # scanner 의 line-level downgrade 가 이미 동작 — critical/high 만 보면
            # "op:// signal 도 없이 raw secret 이 있다" 라는 의미
            blocking = [f for f in findings if f.severity in ("critical", "high")]
            if not blocking:
                continue
            lines = sorted({f.line_number for f in blocking})
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=(
                        f"raw secret {len(blocking)}건 발견 (line "
                        f"{', '.join(str(l) for l in lines[:5])}"
                        f"{'…' if len(lines) > 5 else ''})"
                    ),
                    location=p,
                    suggestion=(
                        "raw token 을 1Password Secret Reference 로 치환 권장: "
                        '"op://<vault>/<item>/<field>". '
                        "대안: anvyc.yaml security.sops + tools.<X>.secret_files."
                    ),
                )
            )
        return results
