"""Project-level connection 정합성 검증 (P7, v0.8.1).

`anvyc project doctor [--path P]` — cwd (또는 명시 path) 의 connection 정합성
13 check. 기존 `anvyc doctor` 는 global health check, project_doctor 는 path-aware.

Check list (D14):
1. aws_profile_defined        .envrc AWS_PROFILE ↔ ~/.aws/config
1b. aws_account_status        인증 방식별 연결 상태 (SSO 토큰/static/assume-role/process)
2. github_remote_parseable    origin URL parse 가능 여부
3. gh_account_routing         origin ssh alias ↔ .envrc GH_CONFIG_DIR
3b. gh_identity_actual        gh 프로필 토큰의 실체(API 역조회) ↔ 선언 계정 대조
4. claude_account_dir_exists  .envrc CLAUDE_CONFIG_DIR → config 디렉터리 존재
5. pulumi_stacks_valid        stack 이름 영숫자/하이픈 (특수문자 X)
6. pulumi_backend_routing     Pulumi.yaml backend ↔ .envrc PULUMI_BACKEND_URL
7. dev_env_secret_safety      .envrc 안 raw secret without op://
8. tool_versions_installed    python/node binary 의 PATH 존재
8b. ownership_declared        origin 있는 저장소가 manifest 에 선언돼 커밋 신원이 결정되는지
9. commit_identity_actual     manifest 선언 커밋 이메일 ↔ 실제 커밋 신원(GIT_AUTHOR_IDENT) 대조
9b. public_repo_email_exposure 공개 저장소 커밋에 개인 이메일이 박히는지
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from anvyc.checks.base import CheckResult, Severity
from anvyc.core import account_manifest, identity_cache, identity_probe
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
    #
    # AWS 기대값은 **의도적으로 없다**. 설계 §6.4 "차단 범위" 가 AWS 를 명시적으로
    # 제외한다 — "제외  AWS 변경 — aws-prod-account-confirm.sh 가 이미 담당
    # (중복 게이트 금지)". `expected_aws_profile` 을 방출하면 훅의 `aws-profile` kind
    # 가 깨어나 manifest `uses.aws` 에 선언된 프로필을 쓴 `aws s3 ls --profile
    # whatap-dev` 조차 deny 된다(§9 는 "선언에 없는 도구 자격 → warn 후 allow" 로
    # 규정). AWS 프로필 관측 자체는 `aws_profile_defined`/`aws_account_status` check
    # 결과로 이미 보고된다 — 빠진 것처럼 보여도 되살리지 말 것.
    expected_gh_user: str | None = None
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
        for key in ("expected_gh_user", "expected_commit_email"):
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


def _gh_profile_hosts_files(expanded_dir: Path) -> tuple[Path, ...]:
    """`expanded_dir` 와 형제 gh 프로필 전체의 `hosts.yml` 경로 집합 (무효화 트리거 후보).

    gh CLI 는 `GH_CONFIG_DIR` 로 라벨(어느 계정으로 표시할지)만 프로필별로 나누고,
    실제 토큰은 OS 키체인에 저장해 **모든 프로필이 공유**한다(2026-08-12 재실측 —
    `gh-heisgone` 프로필에서 재로그인하면 `gh-16bitdo` 프로필의 `gh api user` 응답도
    함께 `heisgone` 으로 바뀐다; `hosts.yml` 자체에는 토큰이 없고 `users:`/`user:`
    라벨만 있다). 즉 "이 프로필의 `hosts.yml` 만" 봐서는 형제 프로필에서의 재인증으로
    이 프로필의 실체가 바뀐 것을 못 본다.

    부모 디렉터리 한 단계만 얕게 glob(`gh*/hosts.yml`) — 홈 디렉터리 전체를 훑지
    않는다. 프로필이 하나도 인증 안 됐으면(파일 없음) 빈 tuple.
    """
    parent = expanded_dir.parent
    try:
        return tuple(sorted(parent.glob("gh*/hosts.yml")))
    except OSError:
        return ()


def _expected_gh_login(
    info: ProjectInfo, resolved: account_manifest.ResolvedAccount | None
) -> tuple[str, str]:
    """실체와 대조할 **기대값**과 그 출처 라벨.

    판정 기준(SoT)은 L1 manifest 의 ownership 이다. `.envrc` 는 머신 로컬 **라벨**일
    뿐 권위가 아니다 — 라벨을 기대값으로 쓰면 라벨 자신과 실체를 비교하는 꼴이라,
    `.envrc` 가 통째로 다른 계정으로 드리프트하면 그 계정 프로필을 조회해 그 계정을
    얻고 "일치" 로 판정한다. 게이트가 스스로를 무력화한다(최종 리뷰 C1).

    manifest 에 ownership 선언이 없거나(미등록 저장소) 이 머신 바인딩에
    `github_login` 이 없을 때만 라벨로 폴백한다 — 폴백이 없으면 미등록 저장소에서
    기대값이 비어 항상 불일치가 되는 오탐 차단이 된다.

    폴백 사유는 두 가지이고 조치가 서로 다르므로 라벨에서 구분한다 — 저장소가 L1
    manifest 에 아예 없는 것(→ manifest 에 등록)과, 선언은 있는데 이 머신 바인딩에
    `github_login` 이 없거나 못 쓰는 값인 것(→ 바인딩 수정)이다. 둘을 뭉뚱그리면
    "미선언" 이라고 적힌 것을 보고 manifest 를 열었다가 이미 있는 것을 발견한다.
    """
    if resolved is not None and resolved.github_login:
        return resolved.github_login, f"manifest ownership '{resolved.ownership_id}'"
    if resolved is not None:
        return (
            str(info.gh_account),
            f".envrc GH_CONFIG_DIR 라벨 (ownership '{resolved.ownership_id}' 선언은 "
            "있으나 이 머신 바인딩에 github_login 없음 — 폴백)",
        )
    return str(info.gh_account), ".envrc GH_CONFIG_DIR 라벨 (manifest 미등록 폴백)"


def _check_gh_identity_actual(
    info: ProjectInfo, resolved: account_manifest.ResolvedAccount | None
) -> list[CheckResult]:
    """선언된 gh 계정과 그 프로필 토큰의 **실체**가 일치하는지.

    `gh_account_routing` 은 .envrc ↔ ssh alias 라벨 정합만 본다. 라벨이 전부 맞아도
    프로필 안의 토큰이 다른 계정일 수 있다(2026-08-12 사고 ③). 여기서만 사슬 밖으로
    나가 "그 이름이 가리키는 것이 실제로 그것인가"를 묻는다.

    **조회 위치와 비교 대상은 서로 다른 것에서 온다** — 이 구분이 이 check 의 핵심이다:

    - 조회 위치 = `.envrc` 라벨 프로필. "지금 이 프로젝트에서 실제로 쓰일 프로필" 을
      봐야 하기 때문. 여기까지 ownership 으로 바꾸면 드리프트한 프로필을 아예 안 보게
      되어 검출이 사라진다.
    - 비교 대상 = manifest ownership (`_expected_gh_login`). 라벨끼리 비교하면 게이트가
      무력화된다.

    - gh_account 미선언 → 검증 대상 X (silent)
    - 조회 실패 → INFO (모름이지 불일치가 아니다)
    - 일치 → INFO · 불일치 → CRITICAL (blocking)
    """
    if not info.gh_account:
        return []
    # gh_config_dir_for_account() 는 `.envrc`/suggestion 에 그대로 쓸 리터럴
    # "$HOME/..." 문자열을 돌려준다(direnv 가 나중에 셸에서 확장하는 것을 전제).
    # 여기서는 subprocess env·파일 mtime 조회처럼 실제 파일시스템 경로가 필요하므로
    # expand_envrc_path() 로 직접 확장해야 한다 — Path.expanduser() 는 선행 `~` 만
    # 확장하고 `$HOME` 리터럴은 그대로 두므로 대신 쓸 수 없다(실측 확인:
    # Path("$HOME/x").expanduser() == Path("$HOME/x")).
    config_dir = gh_config_dir_for_account(info.gh_account)
    expanded_dir = expand_envrc_path(config_dir)
    # 무효화 기준을 디렉터리가 아니라 hosts.yml 파일로 잡는다. POSIX 에서 디렉터리
    # mtime 은 엔트리 추가·삭제·rename 에만 갱신되고 기존 파일의 in-place 수정에는
    # 반응하지 않는다(실측 확인). gh 가 in-place 로 쓰면 재인증 직후에도 캐시가
    # 최대 TTL 동안 옛 신원을 유지한다 — 무효화가 가장 필요한 순간에 실패한다.
    # 파일 mtime 은 in-place 쓰기와 atomic replace 양쪽 모두에서 갱신된다.
    #
    # 그런데 "이 프로필의 hosts.yml 만" 도 한 겹 얕았다(2026-08-12 재실측) — gh 는
    # 토큰을 OS 키체인에 저장해 모든 gh-* 프로필이 공유한다. 다른 프로필에서
    # 재인증해도 이 프로필의 hosts.yml 은 안 바뀌는데 실체(API 응답)는 함께
    # 바뀐다 — 하필 이 check 가 잡아야 하는 바로 그 순간(자격이 막 바뀐 직후)에
    # 무효화가 실패한다. 그래서 이 프로필 하나가 아니라 형제 프로필 전체의
    # hosts.yml 을 source 로 넘긴다(OR 무효화 — identity_cache.probe_cached 참고).
    actual = identity_cache.probe_cached(
        # 키는 비교 대상(ownership)이 아니라 **조회 대상**(이 config 디렉터리)에서
        # 파생한다 — 전역 check 과 같은 함수를 써 네임스페이스를 통일한다.
        key=identity_cache.gh_probe_key(expanded_dir),
        source=_gh_profile_hosts_files(expanded_dir),
        probe=lambda: identity_probe.gh_login(expanded_dir),
    )
    expected, expected_origin = _expected_gh_login(info, resolved)
    if actual is None:
        return [
            CheckResult(
                check_name="gh_identity_actual",
                severity=Severity.INFO,
                message=(
                    f"gh 프로필 'gh-{info.gh_account}' 실체 확인 불가 "
                    "(gh 미설치·미인증·네트워크) — 미검증"
                ),
            )
        ]
    # 대소문자 무시 비교 — 근거는 account_manifest.same_identity 참고.
    if account_manifest.same_identity(expected, actual):
        return [
            CheckResult(
                check_name="gh_identity_actual",
                severity=Severity.INFO,
                message=(
                    f"gh 신원 일치 — 조회 프로필 'gh-{info.gh_account}' 의 실체 "
                    f"'{actual}' == 기대 '{expected}' ({expected_origin})"
                ),
            )
        ]
    # 세 값을 구분해 보여준다 — 조회한 프로필(.envrc 라벨) / 실체 / 기대(+출처).
    # 셋을 뭉뚱그리면 사용자가 `.envrc` 를 고쳐야 하는지 재인증해야 하는지 모른다.
    if expected != info.gh_account:
        suggestion = (
            f".envrc 라벨 'gh-{info.gh_account}' 가 ownership '{expected}' 와 다릅니다 — "
            f'export GH_CONFIG_DIR="{gh_config_dir_for_account(expected)}" 로 수정 후 '
            f"direnv allow. 라벨을 고쳐도 그 프로필의 실체가 '{expected}' 가 아니면 "
            f'GH_CONFIG_DIR="{gh_config_dir_for_account(expected)}" '
            "gh auth login -h github.com -p ssh 로 재인증 "
            "(자격 작업이므로 사용자가 직접 실행)"
        )
    else:
        suggestion = (
            f'GH_CONFIG_DIR="{config_dir}" gh auth login -h github.com -p ssh '
            "로 재인증 (자격 작업이므로 사용자가 직접 실행)"
        )
    return [
        CheckResult(
            check_name="gh_identity_actual",
            severity=Severity.CRITICAL,
            message=(
                f"gh 신원 불일치 — 조회 프로필 'gh-{info.gh_account}'(.envrc 라벨)의 "
                f"실체는 '{actual}' 이나 기대는 '{expected}' ({expected_origin})"
            ),
            suggestion=suggestion,
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


def _origin_repo_slug(info: ProjectInfo) -> str | None:
    """origin remote 에서 `owner/repo` 추출. 프로젝트 식별은 cwd 가 아니라 remote 로 한다.

    worktree·심볼릭 링크·중첩 저장소에서 어긋나지 않고, 판정 기준을 "어디에 있는가"가
    아니라 "어디로 나가는가"에 둔다 — includeIf 를 hasconfig:remote 로 잡은 것과 같다.

    linked worktree(`.git` 이 `gitdir:` 포인터 파일)에서도 `project_info` 가 공통
    git 디렉터리까지 따라가 remote 를 읽으므로(Task 14) `info.github` 가 채워진다.
    """
    for remote in info.github or []:
        if remote.get("name") != "origin":
            continue
        owner, repo = remote.get("owner"), remote.get("repo")
        if owner and repo:
            return f"{owner}/{repo}"
    return None


_NOREPLY_SUFFIX = "@users.noreply.github.com"
# visibility 도 계정의 이메일 공개 설정도 사람이 손으로 바꾸는 값이라 거의 안 움직인다.
# 기본 8h 보다 길게 잡아 `project doctor` 가 훅 경로에서 매번 gh 를 때리지 않게 한다.
_PUBLIC_EXPOSURE_TTL = 24 * 3600


def _check_public_repo_email_exposure(
    path: Path, slug: str | None, resolved: account_manifest.ResolvedAccount | None
) -> list[CheckResult]:
    """공개 저장소 커밋에 **개인 이메일이 박히는지** 확인.

    2026-08-18: `16bitdo/homebrew-anvyc` 가 PUBLIC 인데 개인 주소로 커밋하고 있었다.
    같은 계정의 `16bitdo/anvyc` 는 noreply 를 써서 막고 있었으니 규칙을 어긴 게
    아니라 **규칙이 코드에 없어서** 한쪽만 지켜진 것이다. 커밋에 한 번 박히면
    히스토리 재작성 전까지 남고, 공개 저장소라 그사이 색인된다.

    판정 근거를 `-public` 같은 **이름 규칙에 두지 않는다** — 그건 이 환경에서만
    참이고 다른 사람의 manifest 에서는 조용히 틀린다. 대신 GitHub 계정 자신의 설정을
    본다: `user.email` 이 null 이면 "Keep my email addresses private" 가 켜진 것이고,
    그 설정이 곧 노출을 원치 않는다는 선언이다. 이메일을 공개해 둔 계정에서는 이
    check 가 침묵한다 — 그 사람에게는 위반이 아니기 때문이다.

    - 선언 이메일이 noreply → 노출 자체가 없다 (silent)
    - 저장소가 PUBLIC 이 아님 / 조회 실패 → silent (모름을 위반으로 바꾸지 않는다)
    - 계정이 이메일을 공개 → silent
    - PUBLIC + 실주소 + 계정은 비공개 설정 → WARNING
    """
    if not slug or resolved is None or not resolved.commit_email:
        return []
    if resolved.commit_email.endswith(_NOREPLY_SUFFIX):
        return []
    if resolved.gh_config_dir is None:
        return []
    gh_dir = resolved.gh_config_dir
    visibility = identity_cache.probe_cached(
        # 이 저장소는 probe_cached 를 전부 keyword 로 부른다 — spy 기반 테스트가
        # 인자 이름으로 "캐시 키를 조회 대상에서 파생했는가" 를 검증하기 때문이다.
        key=f"repo-visibility:{slug}",
        source=None,  # 원격 상태라 무효화할 로컬 파일이 없다 — TTL 만 본다
        probe=lambda: identity_probe.repo_visibility(slug, gh_dir),
        ttl=_PUBLIC_EXPOSURE_TTL,
    )
    if visibility != "PUBLIC":
        return []
    account_email = identity_cache.probe_cached(
        key=f"account-email-setting:{gh_dir}",
        source=None,
        probe=lambda: identity_probe.account_email_setting(gh_dir),
        ttl=_PUBLIC_EXPOSURE_TTL,
    )
    if account_email != "PRIVATE":
        return []
    return [
        CheckResult(
            check_name="public_repo_email_exposure",
            severity=Severity.WARNING,
            message=(
                f"{slug}: 공개 저장소인데 커밋 이메일이 실주소다 "
                f"('{resolved.commit_email}', ownership '{resolved.ownership_id}') — "
                "이 계정은 이메일을 비공개로 두고 있다"
            ),
            location=path,
            suggestion=(
                "공개 저장소용 ownership 을 따로 선언하고 그 바인딩의 commit_email 을 "
                f"'<id>+<login>{_NOREPLY_SUFFIX}' 로 두세요. 이미 커밋된 주소는 "
                "히스토리 재작성 전까지 남습니다."
            ),
        )
    ]


def _check_ownership_declared(
    path: Path, slug: str | None, resolved: account_manifest.ResolvedAccount | None
) -> list[CheckResult]:
    """origin 이 있는 저장소의 커밋 신원이 **manifest 로 결정되는지** 확인.

    `commit_identity_actual` 은 선언된 이메일과 실체를 대조한다 — 선언이 없으면 대조할
    기준이 없어 조용히 건너뛴다. 그런데 신원이 잘못 박히는 경로가 바로 그 "선언 없음"
    이다: ownership 이 없으면 커밋 계정이 `~/.gitconfig` 전역 기본값으로 떨어지고,
    아무도 그 상태를 보고하지 않는다.

    2026-08-18 에 16bitdo 소유 저장소 12곳에서 148개 커밋이 그렇게 다른 신원으로
    기록됐다 — 그 12곳은 전부 manifest 미선언이라 `commit_identity_actual` 이 한 번도
    실행되지 않았다. 가드가 없었던 게 아니라, 가드가 켜지는 조건이 사고가 나는 조건과
    정확히 배타였다.

    - origin 없음 → 대상 X (GitHub 계정 라우팅 자체가 없다)
    - 미선언 / 바인딩에 commit_email 없음 → WARNING
    - 선언 + commit_email 있음 → silent (`commit_identity_actual` 이 실체를 보고한다)
    """
    if not slug:
        return []
    if resolved is None:
        return [
            CheckResult(
                check_name="ownership_declared",
                severity=Severity.WARNING,
                message=(
                    f"{slug}: ownership 미선언 — 커밋 계정이 전역 기본값으로 떨어지고 "
                    "신원 대조(commit_identity_actual)가 건너뛰어진다"
                ),
                location=path,
                suggestion=(
                    "L1 SoT (role-based-ruleset 의 metadata/account-routing.yaml) 에 "
                    "이 저장소를 등록하세요."
                ),
            )
        ]
    if not resolved.commit_email:
        return [
            CheckResult(
                check_name="ownership_declared",
                severity=Severity.WARNING,
                message=(
                    f"{slug}: ownership '{resolved.ownership_id}' 은 선언됐으나 이 머신의 "
                    "바인딩에 commit_email 이 없어 신원 대조가 건너뛰어진다"
                ),
                location=path,
                suggestion=(
                    "L2 바인딩(~/.config/anvyc/accounts/bindings.<hostname>.yaml) 의 해당 "
                    "ownership 에 commit_email 을 추가하세요."
                ),
            )
        ]
    return []


def _check_commit_identity_actual(
    path: Path, slug: str | None, resolved: account_manifest.ResolvedAccount | None
) -> list[CheckResult]:
    """manifest 가 선언한 ownership 커밋 이메일과 **실제로 커밋될 신원** 대조.

    `slug`/`resolved` 는 orchestrator 가 한 번만 계산해 내려준다 — check 마다 다시
    `resolve()` 를 부르면 훅이 Bash 명령마다 호출하는 경로에서 YAML 파싱이 배수로 늘고,
    같은 실행 안에서 서로 다른 manifest 스냅샷을 볼 여지도 생긴다.

    - 저장소 미선언 / 바인딩에 commit_email 없음 → 검증 대상 X (silent)
    - 신원 미해결 → WARNING (fail-closed 라 커밋 자체가 안 되는 상태)
    - 일치 → INFO · 불일치 → CRITICAL
    """
    if not slug or resolved is None or not resolved.commit_email:
        return []
    actual = identity_probe.commit_email(path)
    if actual is None:
        return [
            CheckResult(
                check_name="commit_identity_actual",
                severity=Severity.WARNING,
                message=(
                    f"{slug}: 커밋 신원 미해결 (fail-closed) — "
                    f"선언 '{resolved.commit_email}' 이나 이 저장소에서 커밋이 거부된다"
                ),
                location=path,
                suggestion=(
                    "~/.gitconfig 의 includeIf 가 이 저장소의 remote 를 커버하는지 확인 "
                    "(git config --show-origin --get user.email)"
                ),
            )
        ]
    # 대소문자 무시 비교 — GitHub 은 커밋 이메일도 대소문자 무시로 매칭한다.
    if account_manifest.same_identity(resolved.commit_email, actual):
        return [
            CheckResult(
                check_name="commit_identity_actual",
                severity=Severity.INFO,
                message=f"{slug}: 커밋 신원 일치 ({actual}, ownership '{resolved.ownership_id}')",
            )
        ]
    return [
        CheckResult(
            check_name="commit_identity_actual",
            severity=Severity.CRITICAL,
            message=(
                f"{slug}: 커밋 신원 불일치 — 선언 '{resolved.commit_email}' "
                f"(ownership '{resolved.ownership_id}') 이나 실제 '{actual}'"
            ),
            location=path,
            suggestion=(
                "커밋 전 git config --show-origin --get user.email 로 출처를 확인하세요. "
                "잘못된 신원으로 커밋하면 히스토리 정정 비용이 큽니다."
            ),
        )
    ]


# ---------- orchestrator ----------------------------------------------------


def run_project_doctor(path: Path) -> ProjectDoctorReport:
    """11 check 를 순차 실행. raw secret 검증 위해 redact_secrets=False 로 수집."""
    info = collect_project_info(path, redact_secrets=False)
    report = ProjectDoctorReport(path=path.resolve())
    # 판정 기준(SoT)인 L1 manifest 를 **여기서 한 번만** 로드해 소비처(gh 실체 대조 ·
    # 커밋 신원 대조 · expected_* 방출)에 내려준다. check 안에서 각자 resolve() 를
    # 부르면 훅이 Bash 명령마다 호출하는 경로에서 YAML 파싱이 배수로 늘어난다.
    slug = _origin_repo_slug(info)
    resolved = account_manifest.resolve(slug) if slug else None
    report.results.extend(_check_aws_profile_defined(info))
    report.results.extend(_check_aws_account_status(info))
    report.results.extend(_check_github_remote_parseable(info))
    report.results.extend(_check_gh_account_routing(info))
    report.results.extend(_check_gh_identity_actual(info, resolved))
    report.results.extend(_check_claude_account_dir_exists(info))
    report.results.extend(_check_pulumi_stacks_valid(info))
    report.results.extend(_check_pulumi_backend_routing(info))
    report.results.extend(_check_dev_env_secret_safety(info))
    report.results.extend(_check_tool_versions_installed(info))
    report.results.extend(_check_ownership_declared(path, slug, resolved))
    report.results.extend(_check_commit_identity_actual(path, slug, resolved))
    report.results.extend(_check_public_repo_email_exposure(path, slug, resolved))
    # expected_* — 선언된 기대값(실체 아님). 훅이 명령에서 뽑은 detected 와 비교한다.
    # AWS 는 여기서 방출하지 않는다 (설계 §6.4 제외 — ProjectDoctorReport 주석 참조).
    report.expected_gh_user = info.gh_account
    if resolved is not None:
        report.expected_commit_email = resolved.commit_email
        # manifest ownership 이 있으면 .envrc 라벨보다 우선한다 (L1 이 SoT).
        if resolved.github_login:
            report.expected_gh_user = resolved.github_login
    return report
