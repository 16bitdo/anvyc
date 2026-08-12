"""계정 라우팅 manifest 2층 로더 — L1 프로젝트맵 + 머신 바인딩.

Layer A (L1 정책, 머신 무관): role-based-ruleset/metadata/account-routing.yaml
    프로젝트 -> 논리 계정 ID
Layer B (L2 환경, 머신 종속): ~/.config/anvyc/accounts/bindings.<hostname>.yaml
    논리 계정 ID -> 이 머신의 물리 자격 위치

논리 계정 ID 가 두 층의 유일한 접점이다. 프로젝트맵은 이름만 알고 경로를 모른다 —
새 머신은 바인딩 파일 하나만 쓰면 되고 프로젝트맵은 손대지 않는다.

바인딩 파일은 public identifier(로그인명·이메일·alias·경로)만 담는 것이 정책이다.
이 로더도 그 정책에 맞춰 그런 필드만 읽는다 — ResolvedAccount 에는 애초에 토큰·키
필드가 없다. 다만 이 모듈은 바인딩 파일 자체에 비밀이 섞여 있는지 스캔·검증하지는
않는다 — rule 27 §1(자격 본문 sync 금지)의 전제이자 sync 적격 조건일 뿐이다.
"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_MANIFEST = Path.home() / "dev" / "role-based-ruleset" / "metadata" / "account-routing.yaml"
_DEFAULT_BINDINGS_DIR = Path.home() / ".config" / "anvyc" / "accounts"


@dataclass(frozen=True)
class ProjectAccount:
    project_id: str
    repo: str
    ownership: str
    uses: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedAccount:
    ownership_id: str
    github_login: str | None = None
    commit_email: str | None = None
    ssh_alias: str | None = None
    gh_config_dir: Path | None = None
    claude_config_dir: Path | None = None


def machine_name() -> str:
    return socket.gethostname().split(".")[0]


def manifest_path() -> Path:
    override = os.environ.get("ANVYC_ACCOUNT_MANIFEST")
    return Path(override) if override else _DEFAULT_MANIFEST


def bindings_path() -> Path:
    override = os.environ.get("ANVYC_ACCOUNT_BINDINGS_DIR")
    root = Path(override) if override else _DEFAULT_BINDINGS_DIR
    return root / f"bindings.{machine_name()}.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def load_projects() -> dict[str, ProjectAccount]:
    """`owner/repo` -> ProjectAccount. manifest 부재·파손 시 빈 dict."""
    data = _read_yaml(manifest_path())
    out: dict[str, ProjectAccount] = {}
    for p in data.get("projects") or []:
        if not isinstance(p, dict):
            continue
        repo, ownership = p.get("repo"), p.get("ownership")
        if not isinstance(repo, str) or not isinstance(ownership, str):
            continue
        uses = p.get("uses")
        out[repo] = ProjectAccount(
            project_id=str(p.get("id") or repo),
            repo=repo,
            ownership=ownership,
            uses=uses if isinstance(uses, dict) else {},
        )
    return out


def load_bindings() -> dict[str, dict[str, Any]]:
    """논리 계정 ID -> 바인딩 매핑. 부재 시 빈 dict."""
    accounts = _read_yaml(bindings_path()).get("accounts")
    return accounts if isinstance(accounts, dict) else {}


def _expand(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(os.path.expanduser(os.path.expandvars(value)))


def resolve(repo_slug: str) -> ResolvedAccount | None:
    """`owner/repo` -> 이 머신에서의 ownership 자격. 미선언이면 None.

    선언은 있으나 이 머신 바인딩이 없으면 ownership_id 만 채운 부분 결과를 준다 —
    "선언은 됐는데 이 머신에 자격이 없다"를 "미선언"과 구분하기 위해서다.
    """
    project = load_projects().get(repo_slug)
    if project is None:
        return None
    binding = load_bindings().get(project.ownership)
    if not isinstance(binding, dict):
        return ResolvedAccount(ownership_id=project.ownership)
    return ResolvedAccount(
        ownership_id=project.ownership,
        github_login=binding.get("github_login") or None,
        commit_email=binding.get("commit_email") or None,
        ssh_alias=binding.get("ssh_alias") or None,
        gh_config_dir=_expand(binding.get("gh_config_dir")),
        claude_config_dir=_expand(binding.get("claude_config_dir")),
    )
