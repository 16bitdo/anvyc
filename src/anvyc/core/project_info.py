"""cwd 의 모든 connection 정보 통합 (P1, v0.8.0).

`anvyc project show` 의 backend — AWS profile / GitHub remote / Pulumi project
/ dev_env 변수 / tool versions 를 하나의 dataclass 로 묶어 JSON dump 가능.

D11c: dev_env 의 값에 anvyc 의 secret PATTERNS 이 매칭되면 `***REDACTED***` 로
자동 마스킹. op:// 1Password reference 는 placeholder 이므로 매칭 제외.
"""
from __future__ import annotations

import re
import subprocess
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
    # 2026-10-23 — 생성된 CLAUDE.md 헤더에서 읽은 룰셋 provenance(role·commit·generated_at) +
    # 배포본 룰 수. 생성물이 아니면(손으로 쓴 CLAUDE.md·부재) None. 신선도는 ruleset_freshness().
    ruleset: dict[str, Any] | None = None


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

    # `.git` 디렉터리든 linked worktree·submodule 의 `gitdir:` 포인터 파일이든
    # parse_git_config 가 해석한다(없거나 해석 실패 → []).
    github_remotes: list[GitRemoteInfo] = parse_git_config(p / ".git")
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
        ruleset=_collect_ruleset(p),
    )


def to_dict(info: ProjectInfo) -> dict[str, Any]:
    return asdict(info)


# ── 룰셋 provenance (role-based-ruleset 리뷰 2026-10-22 항목 4) ───────────────────
#
# 에이전트가 프로젝트 단위로 "내 룰셋 role·commit·신선도" 를 물을 수단이 CLAUDE.md 헤더
# 파싱밖에 없었다. claude-md-freshness 는 global doctor 에서 fleet 전체를 한 문자열로 보고한다.
# 여기서는 헤더만 읽어 provenance 를 구조화하고, 신선도는 비용(rbr 스크립트 1회 실행)이 있어
# 단일 프로젝트 조회(project show)에서만 ruleset_freshness() 로 덧붙인다 — project list 는 안 한다.

_GENERATED_MARKER = "auto-generated from .cursor/rules/"
_HEADER_KEYS = ("role", "generated_at", "ruleset_version", "ruleset_commit")


def _collect_ruleset(p: Path) -> dict[str, Any] | None:
    claude_md = p / "CLAUDE.md"
    if not claude_md.is_file():
        return None
    try:
        with claude_md.open(encoding="utf-8") as fh:
            first, second = fh.readline(), fh.readline()
    except OSError:
        return None
    if _GENERATED_MARKER not in first:
        return None  # 손으로 쓴 CLAUDE.md — 룰셋 산출물이 아니다
    out: dict[str, Any] = {}
    for part in second.strip().removeprefix("<!--").removesuffix("-->").split("|"):
        key, _, val = part.strip().partition(":")
        if key.strip() in _HEADER_KEYS and val.strip():
            out[key.strip()] = val.strip()
    rules_dir = p / ".cursor" / "rules"
    out["cursor_rules"] = len(list(rules_dir.glob("*.mdc"))) if rules_dir.is_dir() else 0
    return out


def _rbr_generate_script() -> Path:
    return Path.home() / "dev" / "role-based-ruleset" / "scripts" / "generate_claude_md.py"


def ruleset_freshness(p: Path) -> bool | None:
    """생성된 CLAUDE.md 가 그 프로젝트 `.cursor/rules` 와 content-fresh 한지. 모르면 None.

    rbr `generate_claude_md.py --target-dir <p> --check` 를 read-only 로 1회 실행한다(exit 0 fresh /
    1 stale). rbr 부재·오류·생성물 아님 → None (모름은 stale 이 아니다).
    """
    if _collect_ruleset(p) is None:
        return None
    script = _rbr_generate_script()
    if not script.is_file():
        return None
    try:
        proc = subprocess.run(
            ["python3", str(script), "--target-dir", str(p), "--check"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None
