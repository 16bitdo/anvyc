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


def _derive_gh_account(gh_config_dir: str | None) -> str | None:
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


def _derive_claude_account(claude_config_dir: str | None) -> str | None:
    """`CLAUDE_CONFIG_DIR` 경로 값 → Claude Code 계정 이름.

    convention: `$HOME/.claude-<account>` → `<account>` (basename 의 `.claude-`
    prefix 제거). 기본 `$HOME/.claude` (suffix 없음) → None.
    basename 이 `.claude-<name>` / `claude-<name>` 형식이 아니면 None.
    `_derive_gh_account` 패턴과 동일 — 경로 값이므로 basename 추출 후 prefix strip.
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
    gh_account = _derive_gh_account(raw_dev_env.get("GH_CONFIG_DIR"))
    # CLAUDE_CONFIG_DIR 경로 값 → Claude Code 계정 (per-project routing). 경로 자체는 secret 아님.
    claude_account = _derive_claude_account(raw_dev_env.get("CLAUDE_CONFIG_DIR"))

    github_remotes: list[GitRemoteInfo] = []
    git_dir = p / ".git"
    if git_dir.is_dir():
        github_remotes = parse_git_config(git_dir)
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
