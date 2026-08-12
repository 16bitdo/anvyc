"""Project-level connection 정합성 검증 (P7, v0.8.1).

`anvyc project doctor [--path P]` — cwd (또는 명시 path) 의 connection 정합성
9 check. 기존 `anvyc doctor` 는 global health check, project_doctor 는 path-aware.

Check list (D14):
1. aws_profile_defined        .envrc AWS_PROFILE ↔ ~/.aws/config
1b. aws_account_status        인증 방식별 연결 상태 (SSO 토큰/static/assume-role/process)
2. github_remote_parseable    origin URL parse 가능 여부
3. gh_account_routing         origin ssh alias ↔ .envrc GH_CONFIG_DIR
4. claude_account_dir_exists  .envrc CLAUDE_CONFIG_DIR → config 디렉터리 존재
5. pulumi_stacks_valid        stack 이름 영숫자/하이픈 (특수문자 X)
6. pulumi_backend_routing     Pulumi.yaml backend ↔ .envrc PULUMI_BACKEND_URL
7. dev_env_secret_safety      .envrc 안 raw secret without op://
8. tool_versions_installed    python/node binary 의 PATH 존재
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from anvyc.checks.base import CheckResult, Severity
from anvyc.core import identity_cache, identity_probe
from anvyc.core.aws_profile_state import evaluate_profile_state, state_to_result
from anvyc.core.project_info import (
    ProjectInfo,
    collect_project_info,
    expand_envrc_path,
    gh_config_dir_for_account,
)
from anvyc.security.patterns import OP_REFERENCE_RE, PATTERNS
from anvyc.utils.aws_config import load_aws_profile_names
from anvyc.utils.pulumi_project import normalize_backend_url

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
    # 훅(account-routing-mismatch.sh)이 소비하는 C2 계약 필드.
    # 값이 없으면 payload 에서 생략한다 — 훅의 "미특정 → allow" 정책을 깨지 않기 위해.
    expected_gh_user: str | None = None
    expected_aws_profile: str | None = None
    expected_commit_email: str | None = None

    def has_blocking(self) -> bool:
        return any(r.severity.is_blocking for r in self.results)

    def to_payload(self) -> dict[str, object]:
        """`--json` 과 MCP 가 공유하는 단일 payload 생성자.

        두 곳에서 각각 조립하면 필드 추가 시 갈린다. 훅은 이 형식을 계약으로 삼는다.
        """
        payload: dict[str, object] = {
            "path": str(self.path),
            "results": [r.to_dict() for r in self.results],
        }
        for key in ("expected_gh_user", "expected_aws_profile", "expected_commit_email"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        return payload


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


def _check_aws_account_status(info: ProjectInfo) -> list[CheckResult]:
    """profile 정의됨일 때 인증 방식·연결 상태 보고. 미정의는 aws_profile_defined 에 위임."""
    if not info.aws_profile:
        return []
    state = evaluate_profile_state(info.aws_profile)
    if not state.defined:
        return []  # 미정의 → aws_profile_defined 가 보고
    res = state_to_result(state, check_name="aws_account_status")
    return [res] if res is not None else []


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


def _check_gh_account_routing(info: ProjectInfo) -> list[CheckResult]:
    """origin remote 의 ssh alias ↔ `.envrc` 의 GH_CONFIG_DIR gh 계정 정합성.

    per-project gh routing: `.envrc` 가 `export GH_CONFIG_DIR="$HOME/.config/gh-<account>"`
    를 선언하면 `gh` CLI 가 project 별 올바른 계정을 사용 (global active account 우회).

    - origin 이 GitHub ssh alias 를 안 씀 → 검증 대상 X (silent, 0 결과)
    - ssh alias 있는데 GH_CONFIG_DIR 없음 → WARNING
    - gh 계정 ≠ ssh alias → WARNING
    - 일치 → INFO
    """
    if not info.github:
        return []
    alias: str | None = None
    for remote in info.github:
        if remote["name"] != "origin":
            continue
        host = remote["host"] or ""
        if host.startswith("github.com"):
            alias = remote["ssh_alias"]
        break
    # origin 이 GitHub ssh alias 를 안 쓰면 routing 검증 불필요
    if not alias:
        return []
    if info.gh_account is None:
        return [
            CheckResult(
                check_name="gh_account_routing",
                severity=Severity.WARNING,
                message=(
                    f"GitHub origin 이 ssh alias '{alias}' 를 쓰지만 "
                    f".envrc 에 GH_CONFIG_DIR 라우팅 선언 없음"
                ),
                suggestion=(
                    f'.envrc 에 export GH_CONFIG_DIR="{gh_config_dir_for_account(alias)}" '
                    f"추가 후 direnv allow (또는 `anvyc project init`)"
                ),
            )
        ]
    if info.gh_account != alias:
        return [
            CheckResult(
                check_name="gh_account_routing",
                severity=Severity.WARNING,
                message=(
                    f".envrc GH_CONFIG_DIR gh 계정 '{info.gh_account}' 가 "
                    f"GitHub origin ssh alias '{alias}' 와 불일치"
                ),
                suggestion=(
                    f'export GH_CONFIG_DIR="{gh_config_dir_for_account(alias)}" 로 수정 '
                    f"(ssh alias 와 일치)"
                ),
            )
        ]
    return [
        CheckResult(
            check_name="gh_account_routing",
            severity=Severity.INFO,
            message=f"gh 계정 라우팅 OK (GH_CONFIG_DIR → '{info.gh_account}' == origin ssh alias)",
        )
    ]


def _check_gh_identity_actual(info: ProjectInfo) -> list[CheckResult]:
    """선언된 gh 계정과 그 프로필 토큰의 **실체**가 일치하는지.

    `gh_account_routing` 은 .envrc ↔ ssh alias 라벨 정합만 본다. 라벨이 전부 맞아도
    프로필 안의 토큰이 다른 계정일 수 있다(2026-08-12 사고 ③). 여기서만 사슬 밖으로
    나가 "그 이름이 가리키는 것이 실제로 그것인가"를 묻는다.

    - gh_account 미선언 → 검증 대상 X (silent)
    - 조회 실패 → INFO (모름이지 불일치가 아니다)
    - 일치 → INFO · 불일치 → CRITICAL (blocking)
    """
    if not info.gh_account:
        return []
    config_dir = gh_config_dir_for_account(info.gh_account)
    # 무효화 기준을 디렉터리가 아니라 hosts.yml 파일로 잡는다. POSIX 에서 디렉터리
    # mtime 은 엔트리 추가·삭제·rename 에만 갱신되고 기존 파일의 in-place 수정에는
    # 반응하지 않는다(실측 확인). gh 가 in-place 로 쓰면 재인증 직후에도 캐시가
    # 최대 TTL 동안 옛 신원을 유지한다 — 무효화가 가장 필요한 순간에 실패한다.
    # 파일 mtime 은 in-place 쓰기와 atomic replace 양쪽 모두에서 갱신된다.
    actual = identity_cache.probe_cached(
        key=f"gh:{info.gh_account}",
        source=Path(config_dir).expanduser() / "hosts.yml",
        probe=lambda: identity_probe.gh_login(config_dir),
    )
    if actual is None:
        return [
            CheckResult(
                check_name="gh_identity_actual",
                severity=Severity.INFO,
                message=(
                    f"gh 계정 '{info.gh_account}' 실체 확인 불가 "
                    "(gh 미설치·미인증·네트워크) — 미검증"
                ),
            )
        ]
    if actual == info.gh_account:
        return [
            CheckResult(
                check_name="gh_identity_actual",
                severity=Severity.INFO,
                message=f"gh 계정 실체 일치: 선언·실체 모두 '{actual}'",
            )
        ]
    return [
        CheckResult(
            check_name="gh_identity_actual",
            severity=Severity.CRITICAL,
            message=(
                f"gh 프로필 'gh-{info.gh_account}' 의 토큰이 실제로는 '{actual}' 계정 — "
                f"선언 '{info.gh_account}' 와 실체 '{actual}' 불일치"
            ),
            suggestion=(
                f'GH_CONFIG_DIR="{config_dir}" gh auth login -h github.com -p ssh '
                "로 재인증 (자격 작업이므로 사용자가 직접 실행)"
            ),
        )
    ]


def _check_claude_account_dir_exists(info: ProjectInfo) -> list[CheckResult]:
    """`.envrc` 의 CLAUDE_CONFIG_DIR 가 가리키는 config 디렉터리 존재 검증.

    per-project Claude routing: `.envrc` 가
    `export CLAUDE_CONFIG_DIR="$HOME/.claude-<account>"` 를 선언하면 Claude Code 가
    project 별 계정(config + auth 토큰)을 사용한다. cross-check 할 "remote" 가
    없으므로 1-way 디렉터리 존재 확인만 한다 (global `project-claude-account-mapping`
    check 의 path-aware 버전).

    - CLAUDE_CONFIG_DIR 미선언 → 검증 대상 X (silent, 0 결과)
    - 디렉터리 존재 → INFO
    - 디렉터리 부재 → WARNING
    """
    raw = info.dev_env.get("CLAUDE_CONFIG_DIR")
    if not raw:
        return []
    resolved = expand_envrc_path(raw)
    label = f" (계정 '{info.claude_account}')" if info.claude_account else ""
    if resolved.is_dir():
        return [
            CheckResult(
                check_name="claude_account_dir_exists",
                severity=Severity.INFO,
                message=(
                    f"Claude 계정 라우팅 OK{label} — "
                    f"CLAUDE_CONFIG_DIR config 디렉터리 존재: {resolved}"
                ),
            )
        ]
    return [
        CheckResult(
            check_name="claude_account_dir_exists",
            severity=Severity.WARNING,
            message=(
                f".envrc CLAUDE_CONFIG_DIR{label} 가 가리키는 "
                f"config 디렉터리 부재: {resolved}"
            ),
            suggestion=(
                f"CLAUDE_CONFIG_DIR={resolved} 로 Claude Code 를 1회 실행해 "
                "계정 config 디렉터리 생성 (claude 로그인)"
            ),
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


def _check_pulumi_backend_routing(info: ProjectInfo) -> list[CheckResult]:
    """`Pulumi.yaml` 의 backend.url 과 `.envrc` 의 PULUMI_BACKEND_URL 정합성.

    per-project Pulumi routing: `Pulumi.yaml` 의 `backend.url` 이 state backend
    (org/account) 를 결정한다. `.envrc` 의 PULUMI_BACKEND_URL 은 env override.
    둘 다 선언되면 일치해야 한다 (2-way 정합성 — gh 수준). global
    `project-pulumi-backend-mapping` check 의 path-aware 버전.

    - Pulumi.yaml 없음 / backend·PULUMI_BACKEND_URL 둘 다 없음 → 검증 대상 X (silent)
    - 한쪽만 선언 → INFO
    - 둘 다, 정규화 후 일치 → INFO
    - 둘 다, 불일치 → WARNING
    """
    if not info.pulumi:
        return []
    yaml_backend = info.pulumi.get("backend")
    envrc_backend = info.dev_env.get("PULUMI_BACKEND_URL")
    if not yaml_backend and not envrc_backend:
        return []
    if yaml_backend and envrc_backend:
        if normalize_backend_url(yaml_backend) == normalize_backend_url(envrc_backend):
            return [
                CheckResult(
                    check_name="pulumi_backend_routing",
                    severity=Severity.INFO,
                    message=(
                        "Pulumi backend 라우팅 OK — Pulumi.yaml ↔ "
                        f".envrc PULUMI_BACKEND_URL 일치: {yaml_backend}"
                    ),
                )
            ]
        return [
            CheckResult(
                check_name="pulumi_backend_routing",
                severity=Severity.WARNING,
                message=(
                    f"Pulumi.yaml backend '{yaml_backend}' 가 "
                    f".envrc PULUMI_BACKEND_URL '{envrc_backend}' 와 불일치"
                ),
                suggestion=(
                    "Pulumi.yaml 의 backend.url 과 .envrc 의 PULUMI_BACKEND_URL 을 "
                    "동일 backend 로 맞추세요 (둘 중 의도한 SoT 기준)."
                ),
            )
        ]
    if yaml_backend:
        return [
            CheckResult(
                check_name="pulumi_backend_routing",
                severity=Severity.INFO,
                message=f"Pulumi.yaml backend 선언: {yaml_backend} (.envrc override 없음)",
            )
        ]
    return [
        CheckResult(
            check_name="pulumi_backend_routing",
            severity=Severity.INFO,
            message=(
                f".envrc PULUMI_BACKEND_URL 선언: {envrc_backend} "
                "(Pulumi.yaml backend 없음)"
            ),
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
    """9 check 를 순차 실행. raw secret 검증 위해 redact_secrets=False 로 수집."""
    info = collect_project_info(path, redact_secrets=False)
    report = ProjectDoctorReport(path=path.resolve())
    report.results.extend(_check_aws_profile_defined(info))
    report.results.extend(_check_aws_account_status(info))
    report.results.extend(_check_github_remote_parseable(info))
    report.results.extend(_check_gh_account_routing(info))
    report.results.extend(_check_gh_identity_actual(info))
    report.results.extend(_check_claude_account_dir_exists(info))
    report.results.extend(_check_pulumi_stacks_valid(info))
    report.results.extend(_check_pulumi_backend_routing(info))
    report.results.extend(_check_dev_env_secret_safety(info))
    report.results.extend(_check_tool_versions_installed(info))
    # expected_* — 선언된 기대값(실체 아님). 훅이 명령에서 뽑은 detected 와 비교한다.
    report.expected_gh_user = info.gh_account
    report.expected_aws_profile = info.aws_profile
    return report
