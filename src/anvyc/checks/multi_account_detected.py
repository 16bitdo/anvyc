"""multi-account-detected check.

다중 계정 환경 (AWS 다 profile, GitHub ssh alias, Cursor user alias symlink,
Claude Code 계정별 config 디렉터리) 을 감지하여 INFO 로 안내. 각 영역은 독립적으로
평가 — 넷 다 발견되면 결과 4건.

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
DEFAULT_CLAUDE_HOME = Path("~").expanduser()

# ssh_config(5): 키워드는 대소문자를 가리지 않고, 인자와는 공백 또는 `=`(앞뒤 공백 선택)로 나뉜다.
# `Host` 한 줄에 패턴이 여럿 올 수 있다. `\s*=\s*|\s+` 라서 `HostName` 같은 다른 키워드는 매치하지 않는다.
_HOST_LINE_RE = re.compile(r"^\s*Host(?:\s*=\s*|\s+)(?P<patterns>.+?)\s*$", re.IGNORECASE)
# Cursor user-keyed project dir: `Users-<user>-<path>` (마지막 세그먼트 무관 — SoT 이전 안전)
_USERS_DIR_RE = re.compile(r"^Users-[^-]+-")

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


def _github_alias_tokens(patterns: str) -> list[str]:
    """`Host` 줄의 패턴 문자열(키워드 뒤 전부) → 감지 결과에 올릴 GitHub ssh 별칭들.

    입력 예: "github.com-a github.com-b" · "github.com !github.com-old" · "github.com-* github.com-a"

    토큰은 OpenSSH 와 같은 규칙으로 읽는다(2026-11-16 `ssh -G` 실측, OpenSSH 10.3):
      - `#` 로 시작하는 토큰부터는 주석 — 주석 속 별칭은 그 블록에 걸리지 않는다
      - 큰따옴표로 감싼 토큰은 벗겨서 본다
      - `!` 로 시작하는 패턴은 그 호스트를 제외한다는 뜻이라 별칭이 아니다(접두사 검사로 걸러진다)
    와일드카드(`*`·`?`) 패턴은 여러 별칭에 설정을 거는 블록이지 별칭이 아니라 올리지 않는다
    — 목록이 실제로 쓰는 별칭만 보여 주게 한다.
    """
    out: list[str] = []
    for token in patterns.split():
        if token.startswith("#"):
            break
        token = token.strip('"')
        if token.startswith("github.com-") and not any(c in token for c in "*?"):
            out.append(token)
    return out


def _read_github_ssh_aliases(ssh_config: Path) -> list[str]:
    if not ssh_config.is_file():
        return []
    try:
        text = ssh_config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[str] = []
    for line in text.splitlines():
        m = _HOST_LINE_RE.match(line)
        if m:
            out.extend(_github_alias_tokens(m.group("patterns")))
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


def _detect_claude_dirs(home: Path) -> CheckResult | None:
    """`~/.claude-<account>` 계정별 config 디렉터리 감지.

    per-project Claude routing convention (`.claude-<account>`) 사용 흔적 —
    suffix 가 붙은 디렉터리가 1개라도 있으면 멀티 계정 의도로 본다
    (GitHub ssh alias / Cursor user alias 와 동일하게 ≥1 에서 발화).
    """
    if not home.is_dir():
        return None
    found: list[str] = []
    try:
        for entry in home.glob(".claude-*"):
            if entry.is_dir():
                found.append(entry.name)
    except (OSError, PermissionError):
        return None
    if not found:
        return None
    found.sort()
    return CheckResult(
        check_name=MultiAccountDetectedCheck.name,
        severity=Severity.INFO,
        message=f"Claude Code 계정별 config 디렉터리 감지: {_sample(found)}",
        location=home,
        suggestion=(
            "프로젝트별 .envrc 에 export CLAUDE_CONFIG_DIR 라우팅 권장 (README §11.7)"
        ),
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

        claude_res = _detect_claude_dirs(DEFAULT_CLAUDE_HOME)
        if claude_res:
            results.append(claude_res)

        return results
