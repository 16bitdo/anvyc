"""project-aws-profile-mapping check.

프로젝트 루트(`project_roots`) 아래 `.envrc` 의 `export AWS_PROFILE=X`
값들이 `~/.aws/config` 에 `[profile X]` 또는 `[default]` 로 정의되어 있는지 검증.

- 정의 OK → INFO 1건 (summary)
- 누락 → 각 누락마다 WARNING (location = .envrc 파일, suggestion 포함)
- `.envrc` 없음 → 결과 0건 (silent)
"""
from __future__ import annotations

import re
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.utils.aws_config import load_aws_profile_names

# 한 줄에 `export AWS_PROFILE=foo` 또는 `export AWS_PROFILE="foo"` 등을 매칭.
# 인용부호 끝나기 전 까지 또는 공백/#/끝까지 캡쳐.
_AWS_PROFILE_RE = re.compile(
    r"""^\s*export\s+AWS_PROFILE\s*=\s*['"]?([^'"\s#]+)""",
    re.MULTILINE,
)


def _read_envrc_profile(envrc: Path) -> str | None:
    """`.envrc` 의 첫 `export AWS_PROFILE=X` 라인에서 X 추출."""
    try:
        text = envrc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _AWS_PROFILE_RE.search(text)
    return m.group(1) if m else None


class ProjectAwsProfileMappingCheck:
    name = "project-aws-profile-mapping"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        from anvyc.core.project_scope import iter_project_dirs

        mappings: list[tuple[Path, str]] = []
        for project_dir in iter_project_dirs(markers=(".envrc",), max_depth=2):
            prof = _read_envrc_profile(project_dir / ".envrc")
            if prof:
                mappings.append((project_dir / ".envrc", prof))

        if not mappings:
            return []

        defined = load_aws_profile_names()
        results: list[CheckResult] = []
        missing: list[tuple[Path, str]] = []

        for envrc, prof in mappings:
            if prof not in defined:
                missing.append((envrc, prof))

        if missing:
            for envrc, prof in missing:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=f".envrc AWS_PROFILE={prof} 가 ~/.aws/config 에 정의 안 됨",
                        location=envrc,
                        suggestion=f"aws configure --profile {prof}  "
                                   f"(또는 ~/.aws/config 에 [profile {prof}] section 추가)",
                    )
                )
        else:
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=(
                        f".envrc {len(mappings)}개 → AWS profile mapping 모두 정의됨 "
                        f"(~/.aws/config)"
                    ),
                )
            )
        return results
