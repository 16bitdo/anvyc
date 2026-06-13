"""claude-md-freshness check (L2 관측, read-only).

role-based-ruleset 의 generate_claude_md.py --check 를 호출해, fleet 의 생성된
CLAUDE.md 가 각 repo .cursor/rules 와 content-fresh 한지 관측한다. stale → WARNING.
anvyc 는 SoT 를 수정하지 않는다(단방향) — 재생성은 사용자/L3 몫.

ruleset-deploy-drift(repo 가 origin 보다 뒤 — 스탬프성 신호) 를 per-file content
정밀 신호로 보완. rbr 부재 / 비정상 exit / 오류 → silent skip(무오탐).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity


def _rbr_script() -> Path:
    return Path.home() / "dev" / "role-based-ruleset" / "scripts" / "generate_claude_md.py"


class ClaudeMdFreshnessCheck:
    """L2(read-only): fleet 생성 CLAUDE.md 가 .cursor/rules 와 일치하는지 관측."""

    name = "claude-md-freshness"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        script = _rbr_script()
        if not script.exists():
            return []
        try:
            proc = subprocess.run(
                ["python3", str(script), "--check"],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if proc.returncode != 1:  # 0=fresh, 2=인자/경로 오류 → 보고 없음(무오탐)
            return []
        stale = [ln.strip()[2:] for ln in proc.stdout.splitlines() if ln.startswith("  - ")]
        n = str(len(stale)) if stale else "1+"
        return [
            CheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                message=(
                    f"생성된 CLAUDE.md {n}건이 .cursor/rules 와 불일치(stale) — "
                    + "; ".join(stale[:5])
                ),
                location=script.parent.parent,
                suggestion=(
                    "python3 ~/dev/role-based-ruleset/scripts/generate_claude_md.py "
                    "--apply 후 각 repo 커밋"
                ),
            )
        ]
