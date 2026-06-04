"""project-claude-account-mapping check.

프로젝트 루트(`project_roots`) 아래 `.envrc` 가 `export CLAUDE_CONFIG_DIR=...`
로 per-project Claude Code 계정 라우팅을 선언했을 때, 그 경로가 가리키는
config 디렉터리가 실제로 존재하는지 검증한다.

per-project Claude routing convention: `.envrc` 가
`export CLAUDE_CONFIG_DIR="$HOME/.claude-<account>"` 를 export → Claude Code 가
project 별로 올바른 계정(config + auth 토큰)을 사용한다.

`project-gh-account-mapping` 의 Claude 아날로그 — 단 cross-check 할 "remote" 가
없으므로 **1-way (디렉터리 존재 확인)** 만 한다:
- 선언된 디렉터리가 모두 존재 → INFO 1건 (summary)
- 디렉터리 부재 → 각 project 마다 WARNING (location = .envrc 파일)
- `.envrc` 에 CLAUDE_CONFIG_DIR 선언한 project 없음 → 결과 0건 (silent)
"""

from __future__ import annotations

import re
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.project_info import expand_envrc_path

# 한 줄에 `export CLAUDE_CONFIG_DIR=foo` 또는 `export CLAUDE_CONFIG_DIR="foo"` 매칭.
# 인용부호 끝 또는 공백/#/끝까지 캡쳐 (`project_gh_account` 와 동일 패턴).
_CLAUDE_CONFIG_DIR_RE = re.compile(
    r"""^\s*export\s+CLAUDE_CONFIG_DIR\s*=\s*['"]?([^'"\s#]+)""",
    re.MULTILINE,
)


def _read_envrc_claude_dir(envrc: Path) -> str | None:
    """`.envrc` 의 첫 `export CLAUDE_CONFIG_DIR=X` 라인 → raw 경로 값.

    CLAUDE_CONFIG_DIR 부재 → None.
    """
    try:
        text = envrc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _CLAUDE_CONFIG_DIR_RE.search(text)
    return m.group(1) if m else None


class ProjectClaudeAccountMappingCheck:
    name = "project-claude-account-mapping"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        from anvyc.core.project_scope import iter_project_dirs

        # CLAUDE_CONFIG_DIR 을 선언한 .envrc 만 검증 대상.
        targets: list[tuple[Path, str]] = []  # (project_dir, raw_value)
        for project_dir in iter_project_dirs(markers=(".envrc",), max_depth=2):
            raw = _read_envrc_claude_dir(project_dir / ".envrc")
            if raw:
                targets.append((project_dir, raw))

        if not targets:
            return []

        missing: list[tuple[Path, Path]] = []  # (project_dir, resolved_dir)
        for project_dir, raw in targets:
            resolved = expand_envrc_path(raw)
            if not resolved.is_dir():
                missing.append((project_dir, resolved))

        if missing:
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=(
                        ".envrc CLAUDE_CONFIG_DIR 가 가리키는 config 디렉터리 부재: "
                        f"{resolved}"
                    ),
                    location=project_dir / ".envrc",
                    suggestion=(
                        f"CLAUDE_CONFIG_DIR={resolved} 로 Claude Code 를 1회 실행해 "
                        "계정 config 디렉터리를 생성 (claude 로그인)"
                    ),
                )
                for project_dir, resolved in missing
            ]
        return [
            CheckResult(
                check_name=self.name,
                severity=Severity.INFO,
                message=(
                    f"Claude 계정 라우팅 project {len(targets)}개 → "
                    ".envrc CLAUDE_CONFIG_DIR config 디렉터리 모두 존재"
                ),
            )
        ]
