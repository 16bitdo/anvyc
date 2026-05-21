"""project-gh-account-mapping check.

프로젝트 루트(`doctor.project_roots`) 아래 `.git` 의 GitHub `origin` remote 가
ssh alias (`github.com-<alias>`) 를 쓰는 project 가, 같은 디렉터리의 `.envrc` 에
`export GH_CONFIG_DIR=...` 로 일치하는 gh 계정 라우팅을 선언했는지 검증.

per-project gh routing convention: `.envrc` 가
`export GH_CONFIG_DIR="$HOME/.config/gh-<account>"` 를 export → `gh` CLI 가
project 별로 올바른 계정을 사용 (`gh` 의 single global active account 우회).

`project-aws-profile-mapping` 의 GitHub 아날로그:
- routing OK (account == ssh alias) → INFO 1건 (summary)
- `.envrc` 에 GH_CONFIG_DIR 없음 → 각 project 마다 WARNING (location = project dir)
- account ≠ ssh alias → 각 mismatch 마다 WARNING (location = .envrc 파일)
- ssh alias 쓰는 GitHub origin 없음 → 결과 0건 (silent)
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.project_roots import resolve_project_roots
from anvyc.utils.git_remote import parse_git_config

_MAX_DEPTH = 3  # <root>/<group>/<project>/.git 까지

# 한 줄에 `export GH_CONFIG_DIR=foo` 또는 `export GH_CONFIG_DIR="foo"` 등을 매칭.
# 인용부호 끝나기 전 까지 또는 공백/#/끝까지 캡쳐.
_GH_CONFIG_DIR_RE = re.compile(
    r"""^\s*export\s+GH_CONFIG_DIR\s*=\s*['"]?([^'"\s#]+)""",
    re.MULTILINE,
)


def _iter_git_dirs(root: Path, max_depth: int = _MAX_DEPTH) -> list[Path]:
    """root 아래 max_depth 까지 `.git` 디렉터리 수집."""
    if not root.is_dir():
        return []
    out: list[Path] = []
    try:
        # rglob 은 depth 제한 없음 — 명시적 depth 비교
        for p in root.rglob(".git"):
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            if len(rel.parts) > max_depth:
                continue
            if p.is_dir():
                out.append(p)
    except (OSError, PermissionError):
        return []
    return sorted(out)


def _origin_ssh_alias(git_dir: Path) -> str | None:
    """`.git/config` 의 `origin` remote 가 github ssh alias 면 그 alias 반환.

    origin 부재 / GitHub 아님 / ssh alias 없음 → None.
    """
    for remote in parse_git_config(git_dir):
        if remote.name != "origin":
            continue
        if not remote.host.startswith("github.com"):
            return None
        return remote.ssh_alias
    return None


def _read_envrc_gh_account(envrc: Path) -> str | None:
    """`.envrc` 의 첫 `export GH_CONFIG_DIR=X` 라인 → gh 계정 이름.

    convention: `$HOME/.config/gh-<account>` → `<account>` (basename 의 `gh-` strip).
    GH_CONFIG_DIR 부재 / basename 이 `gh-<name>` 형식 아님 → None.
    """
    try:
        text = envrc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _GH_CONFIG_DIR_RE.search(text)
    if not m:
        return None
    base = PurePosixPath(m.group(1).rstrip("/")).name
    if not base.startswith("gh-"):
        return None
    account = base[len("gh-") :]
    return account or None


class ProjectGhAccountMappingCheck:
    name = "project-gh-account-mapping"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        git_dirs: list[Path] = []
        seen: set[Path] = set()
        for root_str in resolve_project_roots():
            root = Path(root_str).expanduser()
            for g in _iter_git_dirs(root):
                try:
                    key = g.resolve()
                except OSError:
                    key = g
                if key in seen:
                    continue
                seen.add(key)
                git_dirs.append(g)
        if not git_dirs:
            return []

        # ssh alias 를 쓰는 GitHub origin 보유 project 만 검증 대상.
        # (project_dir, ssh_alias) tuple 수집.
        targets: list[tuple[Path, str]] = []
        for git_dir in git_dirs:
            alias = _origin_ssh_alias(git_dir)
            if alias:
                targets.append((git_dir.parent, alias))

        if not targets:
            return []

        results: list[CheckResult] = []
        missing: list[tuple[Path, str]] = []
        mismatch: list[tuple[Path, str, str]] = []  # (project, declared, expected)

        for project_dir, alias in targets:
            envrc = project_dir / ".envrc"
            account = _read_envrc_gh_account(envrc) if envrc.is_file() else None
            if account is None:
                missing.append((project_dir, alias))
            elif account != alias:
                mismatch.append((project_dir, account, alias))

        if missing or mismatch:
            for project_dir, alias in missing:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=(
                            f"GitHub origin 이 ssh alias '{alias}' 를 쓰지만 "
                            f".envrc 에 GH_CONFIG_DIR 라우팅 선언 없음"
                        ),
                        location=project_dir,
                        suggestion=(
                            f"echo 'export GH_CONFIG_DIR=\"$HOME/.config/gh-{alias}\"' "
                            f">> {project_dir / '.envrc'}  (이후 direnv allow)"
                        ),
                    )
                )
            for project_dir, declared, expected in mismatch:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=(
                            f".envrc GH_CONFIG_DIR gh 계정 '{declared}' 가 "
                            f"GitHub origin ssh alias '{expected}' 와 불일치"
                        ),
                        location=project_dir / ".envrc",
                        suggestion=(
                            f'export GH_CONFIG_DIR="$HOME/.config/gh-{expected}" '
                            f"로 수정 (ssh alias 와 일치)"
                        ),
                    )
                )
        else:
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"GitHub ssh alias project {len(targets)}개 → "
                        f"gh 계정 라우팅 (.envrc GH_CONFIG_DIR) 모두 일치"
                    ),
                )
            )
        return results
