"""multi-account-detected check.

다중 계정 환경 (AWS 다 profile, GitHub ssh alias, Cursor user alias symlink) 을 감지하여
INFO 로 안내. 각 영역은 독립적으로 평가 — 셋 다 발견되면 결과 3건.

scope: anvyc 가 multi-account runtime 처리를 하진 않지만, 사용자가 표준 패턴
(direnv/aws-vault/ssh alias) 을 사용하고 있는지 확인하도록 안내.
"""
from __future__ import annotations

import re
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.utils.aws_config import load_aws_profile_names

DEFAULT_SSH_CONFIG = Path("~/.ssh/config").expanduser()
DEFAULT_CURSOR_PROJECTS = Path("~/.cursor/projects").expanduser()

_GITHUB_HOST_RE = re.compile(r"^\s*Host\s+(github\.com-\S+)\s*$", re.IGNORECASE)
_USERS_DIR_RE = re.compile(r"^Users-([^-]+)-Documents$")

_AWS_THRESHOLD = 2  # default 제외 후 profile 수가 이 이상이면 multi-account 판정
_SAMPLE_N = 3


def _sample(items: list[str], n: int = _SAMPLE_N) -> str:
    if len(items) <= n:
        return ", ".join(items)
    return ", ".join(items[:n]) + f", ... (+{len(items) - n})"


def _detect_aws(profiles: set[str]) -> CheckResult | None:
    non_default = sorted(profiles - {"default"})
    if len(non_default) < _AWS_THRESHOLD:
        return None
    return CheckResult(
        check_name=MultiAccountDetectedCheck.name,
        severity=Severity.INFO,
        message=(
            f"AWS profile {len(profiles)}개 감지 ({_sample(non_default)}) — "
            f"프로젝트별 direnv .envrc 권장 (README §11)"
        ),
    )


def _read_github_ssh_aliases(ssh_config: Path) -> list[str]:
    if not ssh_config.is_file():
        return []
    try:
        text = ssh_config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[str] = []
    for line in text.splitlines():
        m = _GITHUB_HOST_RE.match(line)
        if m:
            # `Host alias1 alias2` 같이 한 줄에 다중 alias 도 가능 — 일단 첫 매치만
            for token in m.group(1).split():
                if token.startswith("github.com-"):
                    out.append(token)
    return sorted(set(out))


def _detect_github_ssh(ssh_config: Path) -> CheckResult | None:
    aliases = _read_github_ssh_aliases(ssh_config)
    if not aliases:
        return None
    return CheckResult(
        check_name=MultiAccountDetectedCheck.name,
        severity=Severity.INFO,
        message=f"GitHub SSH alias 감지: {_sample(aliases)}",
        location=ssh_config,
        suggestion=(
            "owner 별 ssh key 분리 패턴 — git remote 의 host alias 와 일치하는지 확인"
        ),
    )


def _detect_cursor_aliases(cursor_projects: Path) -> CheckResult | None:
    if not cursor_projects.is_dir():
        return None
    aliased: list[str] = []
    try:
        for entry in cursor_projects.iterdir():
            if not entry.is_symlink():
                continue
            if _USERS_DIR_RE.match(entry.name):
                aliased.append(entry.name)
    except (OSError, PermissionError):
        return None
    if not aliased:
        return None
    aliased.sort()
    return CheckResult(
        check_name=MultiAccountDetectedCheck.name,
        severity=Severity.INFO,
        message=f"Cursor user alias symlink 감지: {_sample(aliased)}",
        location=cursor_projects,
    )


class MultiAccountDetectedCheck:
    name = "multi-account-detected"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        results: list[CheckResult] = []

        aws_res = _detect_aws(load_aws_profile_names())
        if aws_res:
            results.append(aws_res)

        gh_res = _detect_github_ssh(DEFAULT_SSH_CONFIG)
        if gh_res:
            results.append(gh_res)

        cursor_res = _detect_cursor_aliases(DEFAULT_CURSOR_PROJECTS)
        if cursor_res:
            results.append(cursor_res)

        return results
