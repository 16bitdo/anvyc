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


def normalize_identity(value: object) -> str | None:
    """바인딩 파일의 신원 값을 비교 가능한 문자열로. 못 쓰는 값이면 None.

    YAML 은 인용부호 없는 값을 타입 추론한다. 전부 숫자인 GitHub 로그인
    (`github_login: 12345`)은 int 로 파싱되는데, 그대로 두면 문자열인 실체와
    영원히 불일치해 **해당 계정이 항상 차단**된다. int 는 문자열로 되돌린다.

    `bool` 은 명시적으로 거부한다 — 파이썬에서 `bool` 은 `int` 의 서브클래스라
    `isinstance(True, int)` 가 참이다. YAML 의 `github_login: yes` 는 `True` 로
    파싱되고, 걸러내지 않으면 `"True"` 라는 신원이 만들어진다.

    앞뒤 공백은 제거한다(`"16bitdo "` 같은 편집 실수). 빈 값은 미선언과 같게 None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def same_identity(declared: str | None, actual: str | None) -> bool:
    """선언된 신원과 관측된 실체가 같은 대상을 가리키는가.

    **대소문자를 무시한다.** GitHub 로그인은 대소문자 구분이 없고 API 는 정규화된
    표기를 돌려준다(실측: `users/16BitDo` -> `16bitdo`). 정확 일치로 비교하면
    바인딩에 `16BitDo` 라고 적은 것만으로 그 계정이 영구 차단된다 — 같은 계정인데
    오탐으로 막는 것이라 fail-closed 의 이득 없이 손해만 남는다.

    오탐 위험이 없는 이유: GitHub 로그인 문자셋은 `[A-Za-z0-9-]` 이고 대소문자만
    다른 두 계정은 존재할 수 없으므로, 소문자화로 서로 다른 신원이 겹칠 일이 없다.
    이메일도 GitHub 이 대소문자 무시로 매칭한다.

    한쪽이라도 비어 있으면 False — "모름"을 "일치"로 승격하지 않는다.
    """
    if not declared or not actual:
        return False
    return declared.strip().lower() == actual.strip().lower()


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
    projects = data.get("projects")
    if not isinstance(projects, list):
        return {}
    out: dict[str, ProjectAccount] = {}
    for p in projects:
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
        github_login=normalize_identity(binding.get("github_login")),
        commit_email=normalize_identity(binding.get("commit_email")),
        ssh_alias=normalize_identity(binding.get("ssh_alias")),
        gh_config_dir=_expand(binding.get("gh_config_dir")),
        claude_config_dir=_expand(binding.get("claude_config_dir")),
    )
