"""Project-level connection 정합성 검증 (P7, v0.8.1).

`anvyc project doctor [--path P]` — cwd (또는 명시 path) 의 connection 정합성
5 check. 기존 `anvyc doctor` 는 global health check, project_doctor 는 path-aware.

Check list (D14):
1. aws_profile_defined        .envrc AWS_PROFILE ↔ ~/.aws/config
2. github_remote_parseable    origin URL parse 가능 여부
3. pulumi_stacks_valid        stack 이름 영숫자/하이픈 (특수문자 X)
4. dev_env_secret_safety      .envrc 안 raw secret without op://
5. tool_versions_installed    python/node binary 의 PATH 존재
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from anvyc.checks.base import CheckResult, Severity
from anvyc.core.project_info import ProjectInfo, collect_project_info
from anvyc.security.patterns import OP_REFERENCE_RE, PATTERNS
from anvyc.utils.aws_config import load_aws_profile_names

_STACK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")
_TOOL_BINARIES = {
    "python": ("python3", "python"),
    "node": ("node",),
    # asdf 는 plugin 별로 다양 — 검증 안 함
}


@dataclass
class ProjectDoctorReport:
    path: Path
    results: list[CheckResult] = field(default_factory=list)

    def has_blocking(self) -> bool:
        return any(r.severity.is_blocking for r in self.results)


# ---------- individual checks -----------------------------------------------


def _check_aws_profile_defined(info: ProjectInfo) -> list[CheckResult]:
    if not info.aws_profile:
        return []
    defined = load_aws_profile_names()
    if info.aws_profile in defined:
        return [
            CheckResult(
                check_name="aws_profile_defined",
                severity=Severity.INFO,
                message=f"AWS_PROFILE={info.aws_profile} 정의됨",
            )
        ]
    return [
        CheckResult(
            check_name="aws_profile_defined",
            severity=Severity.WARNING,
            message=f".envrc AWS_PROFILE={info.aws_profile} 가 ~/.aws/config 에 정의 안 됨",
            suggestion=(
                f"aws configure --profile {info.aws_profile}  "
                f"또는 ~/.aws/config 에 [profile {info.aws_profile}] section 추가"
            ),
        )
    ]


def _check_github_remote_parseable(info: ProjectInfo) -> list[CheckResult]:
    # info.github 가 None 이면 .git 없음 (검증 대상 X) — silent
    if not info.github:
        return []
    # parseable 한 remote 만 info 에 담기므로, info.github 가 비어있지 않으면 모두 OK
    return [
        CheckResult(
            check_name="github_remote_parseable",
            severity=Severity.INFO,
            message=f"GitHub remote {len(info.github)}개 parse OK",
        )
    ]


def _check_pulumi_stacks_valid(info: ProjectInfo) -> list[CheckResult]:
    if not info.pulumi:
        return []
    invalid = [s for s in info.pulumi["stacks"] if not _STACK_NAME_RE.match(s)]
    if not invalid:
        return [
            CheckResult(
                check_name="pulumi_stacks_valid",
                severity=Severity.INFO,
                message=(
                    f"Pulumi project '{info.pulumi['project_name']}' "
                    f"stack {len(info.pulumi['stacks'])}개 OK"
                ),
            )
        ]
    return [
        CheckResult(
            check_name="pulumi_stacks_valid",
            severity=Severity.WARNING,
            message=f"Pulumi stack 이름 형식 위반: {', '.join(invalid)}",
            suggestion="stack 이름은 영숫자/하이픈/언더스코어만 권장.",
        )
    ]


def _check_dev_env_secret_safety(info: ProjectInfo) -> list[CheckResult]:
    """`.envrc` 의 raw secret (op:// reference 없이) → CRITICAL.

    info.dev_env 는 collect_project_info(redact_secrets=False) 라 raw 값.
    dev_env 가 비어있으면 check 자체 skip (silent, 0 결과).
    """
    if not info.dev_env:
        return []
    findings: list[str] = []
    for key, value in info.dev_env.items():
        if not value:
            continue
        if OP_REFERENCE_RE.search(value):
            continue
        sample = f"{key}={value}"
        if any(p.regex.search(sample) for p in PATTERNS):
            findings.append(key)
    if not findings:
        return [
            CheckResult(
                check_name="dev_env_secret_safety",
                severity=Severity.INFO,
                message="dev_env raw secret 없음 (op:// reference 사용)",
            )
        ]
    return [
        CheckResult(
            check_name="dev_env_secret_safety",
            severity=Severity.CRITICAL,
            message=f".envrc 에 raw secret 노출: {', '.join(findings)}",
            suggestion="1Password Secret Reference (op://) 또는 SOPS 로 교체 권장 (README §9.1).",
        )
    ]


def _check_tool_versions_installed(info: ProjectInfo) -> list[CheckResult]:
    if not info.tool_versions:
        return []
    missing: list[str] = []
    for tool in info.tool_versions:
        binaries = _TOOL_BINARIES.get(tool)
        if not binaries:
            continue
        if not any(shutil.which(b) for b in binaries):
            missing.append(tool)
    if not missing:
        return [
            CheckResult(
                check_name="tool_versions_installed",
                severity=Severity.INFO,
                message=f"tool_versions ({len(info.tool_versions)}) 모두 PATH 에서 발견됨",
            )
        ]
    return [
        CheckResult(
            check_name="tool_versions_installed",
            severity=Severity.WARNING,
            message=f"tool_versions 의 binary PATH 부재: {', '.join(missing)}",
            suggestion="asdf install / pyenv install / nvm install 로 설치하세요.",
        )
    ]


# ---------- orchestrator ----------------------------------------------------


def run_project_doctor(path: Path) -> ProjectDoctorReport:
    """5 check 를 순차 실행. raw secret 검증 위해 redact_secrets=False 로 수집."""
    info = collect_project_info(path, redact_secrets=False)
    report = ProjectDoctorReport(path=path.resolve())
    report.results.extend(_check_aws_profile_defined(info))
    report.results.extend(_check_github_remote_parseable(info))
    report.results.extend(_check_pulumi_stacks_valid(info))
    report.results.extend(_check_dev_env_secret_safety(info))
    report.results.extend(_check_tool_versions_installed(info))
    return report
