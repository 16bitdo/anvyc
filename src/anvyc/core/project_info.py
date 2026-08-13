"""cwd 의 모든 connection 정보 통합 (P1, v0.8.0).

`anvyc project show` 의 backend — AWS profile / GitHub remote / Pulumi project
/ dev_env 변수 / tool versions 를 하나의 dataclass 로 묶어 JSON dump 가능.

D11c: dev_env 의 값에 anvyc 의 secret PATTERNS 이 매칭되면 `***REDACTED***` 로
자동 마스킹. op:// 1Password reference 는 placeholder 이므로 매칭 제외.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from anvyc.security.patterns import OP_REFERENCE_RE, PATTERNS
from anvyc.utils.git_remote import GitRemoteInfo, parse_git_config
from anvyc.utils.git_remote import to_dict as _git_to_dict
from anvyc.utils.pulumi_project import detect_pulumi_project
from anvyc.utils.pulumi_project import to_dict as _pulumi_to_dict

_EXPORT_RE = re.compile(
    r"""^\s*export\s+(?P<key>[A-Z_][A-Z0-9_]*)\s*=\s*['"]?(?P<val>[^'"\s#]+)""",
    re.MULTILINE,
)

REDACTED_MARKER = "***REDACTED***"


@dataclass
class ProjectInfo:
    path: str
    aws_profile: str | None
    gh_account: str | None
    claude_account: str | None
    github: list[dict[str, Any]] | None
    pulumi: dict[str, Any] | None
    dev_env: dict[str, str] = field(default_factory=dict)
    tool_versions: dict[str, str] = field(default_factory=dict)


def derive_gh_account(gh_config_dir: str | None) -> str | None:
    """`GH_CONFIG_DIR` 경로 값 → gh 계정 이름.

    convention: `$HOME/.config/gh-<account>` → `<account>` (basename 의 `gh-` prefix 제거).
    값이 없거나 basename 이 `gh-<name>` 형식이 아니면 None.
    AWS_PROFILE 과 달리 경로 값이므로 basename 추출 후 prefix strip 한 단계 더 거친다.
    """
    if not gh_config_dir:
        return None
    base = PurePosixPath(gh_config_dir.rstrip("/")).name
    if not base.startswith("gh-"):
        return None
    account = base[len("gh-"):]
    return account or None


def gh_config_dir_for_account(account: str) -> str:
    """gh account 이름 → `.envrc` 에 쓸 GH_CONFIG_DIR 리터럴 값.

    convention: `<account>` → `$HOME/.config/gh-<account>` (`derive_gh_account` 의 역함수).
    `$HOME` 는 **리터럴로 보존** — direnv 가 확장하고, statusline grep / `_parse_envrc` 는
    basename(`gh-<account>`)만 보므로 portable 해야 한다.
    """
    return f"$HOME/.config/gh-{account}"


def _derive_claude_account(claude_config_dir: str | None) -> str | None:
    """`CLAUDE_CONFIG_DIR` 경로 값 → Claude Code 계정 이름.

    convention: `$HOME/.claude-<account>` → `<account>` (basename 의 `.claude-`
    prefix 제거). 기본 `$HOME/.claude` (suffix 없음) → None.
    basename 이 `.claude-<name>` / `claude-<name>` 형식이 아니면 None.
    `derive_gh_account` 패턴과 동일 — 경로 값이므로 basename 추출 후 prefix strip.
    """
    if not claude_config_dir:
        return None
    base = PurePosixPath(claude_config_dir.rstrip("/")).name
    for prefix in (".claude-", "claude-"):
        if base.startswith(prefix):
            return base[len(prefix) :] or None
    return None


def expand_envrc_path(raw: str) -> Path:
    """`.envrc` 값의 `$HOME` / `${HOME}` / `~` 를 확장해 Path 로 변환.

    `_parse_envrc` 는 shell 확장 전 raw 문자열을 캡처하므로, `CLAUDE_CONFIG_DIR`
    같은 디렉터리 경로를 존재 검증하기 전에 leading `$HOME`/`~` 의 직접 확장이
    필요하다. (값 중간의 변수 참조는 다루지 않는다 — convention 상 leading 만.)
    """
    expanded = raw.strip()
    for token in ("${HOME}", "$HOME"):
        if expanded.startswith(token):
            return Path(str(Path.home()) + expanded[len(token) :])
    return Path(expanded).expanduser()


def _parse_envrc(envrc: Path) -> dict[str, str]:
    """`.envrc` 의 모든 `export KEY=VALUE` 추출."""
    try:
        text = envrc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for m in _EXPORT_RE.finditer(text):
        out[m.group("key")] = m.group("val")
    return out


def resolve_cwd_aws_profiles(start: Path | None = None) -> frozenset[str]:
    """`start`(기본 cwd)에서 상위로 walk-up 해 "실행 중인 프로젝트"의 AWS profile 집합.

    의미 (creds-expiry project-scope, 2026-05-31):
    - 가장 가까운 프로젝트 경계(`.git` 또는 `.envrc`)를 프로젝트 루트로 본다.
    - 그 루트의 `.envrc` 에 `AWS_PROFILE=X` 가 있으면 `frozenset({X})`.
    - 경계는 찾았으나 AWS_PROFILE 미설정(도구 repo 등) → `frozenset()` (= 이 프로젝트는
      AWS profile 미사용 → 호출부에서 aws_sso 검사 silent).
    - 경계 자체를 home/root 까지 못 찾으면 `frozenset()`.

    home 위(상위 공통 디렉터리)의 `.envrc` 를 무관한 프로젝트에 상속하지 않도록 home 에서
    walk-up 을 멈춘다. 반환은 항상 frozenset (None 아님) — 호출부의 "scoping active" 표식은
    CheckContext 필드의 None/frozenset 구분으로 별도 관리.
    """
    try:
        cur = (start or Path.cwd()).resolve()
    except OSError:
        return frozenset()
    home = Path.home().resolve()
    for d in (cur, *cur.parents):
        envrc = d / ".envrc"
        is_boundary = envrc.is_file() or (d / ".git").exists()
        if is_boundary:
            if envrc.is_file():
                prof = _parse_envrc(envrc).get("AWS_PROFILE")
                return frozenset({prof}) if prof else frozenset()
            return frozenset()  # .git 프로젝트, .envrc 없음 → AWS profile 미사용
        if d == home or d == d.parent:
            break
    return frozenset()


def _redact_dev_env(dev_env: dict[str, str]) -> dict[str, str]:
    """D11c — PATTERNS 매칭되는 값은 ***REDACTED*** 로 마스킹.

    op:// 1Password reference 는 placeholder 이므로 redaction 면제.
    """
    out: dict[str, str] = {}
    for key, value in dev_env.items():
        if not value:
            out[key] = value
            continue
        if OP_REFERENCE_RE.search(value):
            out[key] = value
            continue
        sample = f"{key}={value}"
        if any(p.regex.search(sample) for p in PATTERNS):
            out[key] = REDACTED_MARKER
        else:
            out[key] = value
    return out


def _collect_tool_versions(path: Path) -> dict[str, str]:
    """`.python-version` / `.nvmrc` / `.tool-versions` 단순 추출."""
    out: dict[str, str] = {}
    py = path / ".python-version"
    if py.is_file():
        first = py.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        if first:
            out["python"] = first[0].strip()
    nv = path / ".nvmrc"
    if nv.is_file():
        first = nv.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        if first:
            out["node"] = first[0].strip()
    tv = path / ".tool-versions"
    if tv.is_file():
        out["asdf"] = tv.read_text(encoding="utf-8", errors="replace").strip()
    return out


def _resolve_gitdir_pointer(dotgit_file: Path) -> Path | None:
    """`.git` 파일(`gitdir: <path>` 포인터) → remote config 를 읽을 git 디렉터리.

    linked worktree 의 `.git` 은 디렉터리가 아니라 이 포인터 파일이다(실측:
    `git worktree add` 로 만든 worktree, 2026-08-13). 포인터가 가리키는 디렉터리는
    보통 worktree 전용 사설 gitdir(`<본체>/.git/worktrees/<name>/`)이고, 그 안의
    `commondir` 파일이 remote 설정을 가진 공통 `.git` 디렉터리(본체)를 상대경로로
    가리킨다. `commondir` 이 없으면(예: `.git` 파일 포맷을 공유하는 git submodule
    처럼 포인터 대상 자체가 이미 독립된 config 를 가짐) 포인터가 가리키는 디렉터리를
    그대로 쓴다.

    포인터·commondir 값은 로컬 git 이 쓴 파일이지만 신뢰하지 않는다 — 상대경로는
    각자의 기준 디렉터리(포인터는 이 `.git` 파일의 부모, commondir 은 포인터가
    가리키는 디렉터리)를 기준으로 pathlib `/` 연산만으로 해석한다(prefix 를 잘라내는
    문자열 슬라이싱은 쓰지 않는다 — sync.py 의 path-traversal 회귀 참조). 값이
    `..`/절대경로를 포함해도 별도로 막지 않는다 — 원격 입력이 아니라 로컬 git 이
    쓴 파일이고, 실패해도 아래에서 읽기 전용으로만 쓰인다.

    어느 단계든 실패하면(파일 없음/권한 오류/형식 불일치) 예외를 던지지 않고
    `None` 을 반환한다 — `project_info` 는 `anvyc doctor` 의 offline·non-fatal
    경로라 여기서 죽으면 안 된다. `commondir` 부재는 실패가 아니라 정상 분기다.

    linked worktree 레이아웃으로만 검증했다 — submodule 의 `.git` 파일도 동일
    포인터 형식을 쓰지만 별도로 테스트하지는 않았다.
    """
    try:
        raw = dotgit_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    stripped = raw.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0]
    if not first_line.startswith("gitdir:"):
        return None
    pointer = first_line[len("gitdir:"):].strip()
    if not pointer:
        return None

    try:
        pointer_path = Path(pointer)
    except ValueError:
        return None
    git_dir = pointer_path if pointer_path.is_absolute() else dotgit_file.parent / pointer_path

    commondir_file = git_dir / "commondir"
    try:
        commondir_exists = commondir_file.is_file()
    except OSError:
        return None
    if not commondir_exists:
        return git_dir  # 비-worktree gitdir(예: submodule) — 포인터 대상을 그대로 사용

    try:
        common_raw = commondir_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not common_raw:
        return None
    common_first_line = common_raw.splitlines()[0]

    try:
        common_path = Path(common_first_line)
    except ValueError:
        return None
    return common_path if common_path.is_absolute() else git_dir / common_path


def collect_project_info(path: Path, *, redact_secrets: bool = True) -> ProjectInfo:
    """단일 path 의 모든 connection 정보 통합."""
    p = path.resolve()

    raw_dev_env = _parse_envrc(p / ".envrc") if (p / ".envrc").is_file() else {}
    dev_env = _redact_dev_env(raw_dev_env) if redact_secrets else raw_dev_env

    aws_profile = raw_dev_env.get("AWS_PROFILE")  # AWS_PROFILE 자체는 secret 아님
    # GH_CONFIG_DIR 경로 값 → gh 계정 (per-project gh routing). 경로 자체는 secret 아님.
    gh_account = derive_gh_account(raw_dev_env.get("GH_CONFIG_DIR"))
    # CLAUDE_CONFIG_DIR 경로 값 → Claude Code 계정 (per-project routing). 경로 자체는 secret 아님.
    claude_account = _derive_claude_account(raw_dev_env.get("CLAUDE_CONFIG_DIR"))

    github_remotes: list[GitRemoteInfo] = []
    git_dir = p / ".git"
    if git_dir.is_dir():
        github_remotes = parse_git_config(git_dir)
    elif git_dir.is_file():
        # linked worktree (또는 submodule) — `.git` 이 `gitdir:` 포인터 파일.
        resolved_git_dir = _resolve_gitdir_pointer(git_dir)
        if resolved_git_dir is not None:
            github_remotes = parse_git_config(resolved_git_dir)
    github = [_git_to_dict(r) for r in github_remotes] if github_remotes else None

    # pulumi dict 는 `backend` 키 포함 (Pulumi.yaml 의 backend.url, per-project routing).
    # `.envrc` 의 PULUMI_BACKEND_URL 은 dev_env 에 자동 수집(비-secret), PULUMI_ACCESS_TOKEN
    # 은 secret → D11c redaction 으로 자동 마스킹 (security.patterns.pulumi_token).
    pulumi = _pulumi_to_dict(detect_pulumi_project(p))

    return ProjectInfo(
        path=str(p),
        aws_profile=aws_profile,
        gh_account=gh_account,
        claude_account=claude_account,
        github=github,
        pulumi=pulumi,
        dev_env=dev_env,
        tool_versions=_collect_tool_versions(p),
    )


def to_dict(info: ProjectInfo) -> dict[str, Any]:
    return asdict(info)
