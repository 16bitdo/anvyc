"""project-gh-account-mapping check.

프로젝트 루트(`project_roots`) 아래 `.git` 의 GitHub `origin` remote 가
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

별칭 **미사용** GitHub origin (plain `github.com` / https) 도 `gh_owner_accounts` 에
그 owner 가 등록돼 있으면 WARNING 으로 검출한다 (issue #198). 등록되지 않은 owner 는
종전대로 silent — 매핑을 선언한 owner 에 대해서만 판정하므로 무오탐을 유지한다.
매핑 자체가 비어 있으면 owner 기반 검증(별칭 미사용 검출 + owner↔alias 라우팅)이
전부 skip 되므로, summary INFO 에 그 사실을 함께 표기한다.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.utils.git_remote import GitRemoteInfo, parse_git_config

# 한 줄에 `export GH_CONFIG_DIR=foo` 또는 `export GH_CONFIG_DIR="foo"` 등을 매칭.
# 인용부호 끝나기 전 까지 또는 공백/#/끝까지 캡쳐.
_GH_CONFIG_DIR_RE = re.compile(
    r"""^\s*export\s+GH_CONFIG_DIR\s*=\s*['"]?([^'"\s#]+)""",
    re.MULTILINE,
)


def _origin_github(git_dir: Path) -> GitRemoteInfo | None:
    """origin 이 GitHub remote 면 그 정보를 반환 (ssh alias 유무 무관).

    origin 부재 / GitHub 아님 → None. 별칭 여부는 호출부가 `.ssh_alias` 로 분기한다.
    """
    for remote in parse_git_config(git_dir):
        if remote.name != "origin":
            continue
        if not remote.host.startswith("github.com"):
            return None
        return remote
    return None


def _repo_write_access(owner: str, repo: str, account: str) -> bool | None:
    """routed account(`gh-<account>`)로 `owner/repo` write(push|admin) 권한 보유 여부.

    조회 실패 / 권한 키 부재 → None(불확정). owner↔alias static 불일치 시에만 호출(network).
    """
    import json  # noqa: PLC0415
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    env = {**os.environ, "GH_CONFIG_DIR": os.path.expanduser(f"~/.config/gh-{account}")}
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}", "--jq", ".permissions"],
            capture_output=True, text=True, check=False, timeout=15, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        perm = json.loads(proc.stdout)
    except (ValueError, AttributeError):
        return None
    if not isinstance(perm, dict):
        return None
    return bool(perm.get("push") or perm.get("admin"))


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

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        from anvyc.core.project_scope import iter_project_dirs

        project_dirs = iter_project_dirs(markers=(".git",), max_depth=2)
        if not project_dirs:
            return []

        # GitHub origin 보유 project 를 ssh alias 사용 / 미사용으로 분류.
        targets: list[tuple[Path, str]] = []  # (project_dir, ssh_alias) — alias↔envrc 검증
        routing_targets: list[tuple[Path, str, str, str]] = []  # (dir, alias, owner, repo)
        unaliased: list[tuple[Path, GitRemoteInfo]] = []  # 별칭 없는 GitHub origin
        for project_dir in project_dirs:
            remote = _origin_github(project_dir / ".git")
            if remote is None:
                continue
            if remote.ssh_alias:
                targets.append((project_dir, remote.ssh_alias))
                if remote.owner and remote.repo:
                    routing_targets.append(
                        (project_dir, remote.ssh_alias, remote.owner, remote.repo)
                    )
            elif remote.owner and remote.repo:
                unaliased.append((project_dir, remote))

        if not targets and not unaliased:
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

        # 별칭 미사용 origin — gh_owner_accounts 에 owner 가 등록된 경우만 판정(무오탐 유지).
        unaliased_findings: list[CheckResult] = []
        for project_dir, remote in unaliased:
            exp_alias = ctx.gh_owner_accounts.get(remote.owner)
            if not exp_alias:
                continue
            unaliased_findings.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=(
                        f"{remote.owner}/{remote.repo}: origin 이 별칭 없는 "
                        f"'{remote.host}'({remote.protocol}) — owner '{remote.owner}' 는 "
                        f"alias 'github.com-{exp_alias}' 라우팅이어야 함 "
                        f"(anvyc gh 가 account 를 도출하지 못해 race-immune 경로 사용 불가)"
                    ),
                    location=project_dir,
                    suggestion=(
                        f"git remote set-url origin "
                        f"git@github.com-{exp_alias}:{remote.owner}/{remote.repo}.git"
                        f'  + .envrc 에 export GH_CONFIG_DIR="$HOME/.config/gh-{exp_alias}"'
                        f" (rule 25)"
                    ),
                )
            )

        if missing or mismatch or unaliased_findings:
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
            results.extend(unaliased_findings)
        elif targets:
            # 매핑 미설정이면 owner 기반 검증이 통째로 skip 된다 — clean 오해 방지용 표기.
            skip_note = (
                ""
                if ctx.gh_owner_accounts
                else " · owner 기반 검증은 doctor.gh_owner_accounts 미설정으로 skip"
            )
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"GitHub ssh alias project {len(targets)}개 → "
                        f"gh 계정 라우팅 (.envrc GH_CONFIG_DIR) 모두 일치{skip_note}"
                    ),
                )
            )
        # owner↔alias 라우팅 검증 (rule 25; ctx.gh_owner_accounts 설정 시에만 — 무오탐).
        # static(alias==기대) 우선, 불일치 시에만 dynamic(routed 계정 write 권한) 보강.
        for project_dir, alias, owner, repo in routing_targets:
            exp_alias = ctx.gh_owner_accounts.get(owner)
            if not exp_alias or alias == exp_alias:
                continue
            write = _repo_write_access(owner, repo, alias)
            if write is False:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=(
                            f"{owner}/{repo}: owner '{owner}' 는 alias '{exp_alias}' 라우팅이어야 "
                            f"하나 '{alias}' 사용 — 그 계정 write 권한 없음 (misroute)"
                        ),
                        location=project_dir,
                        suggestion=(
                            f"remote 를 github.com-{exp_alias} 로, .envrc GH_CONFIG_DIR 를 "
                            f"gh-{exp_alias} 로 (rule 25)"
                        ),
                    )
                )
            else:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.INFO,
                        message=(
                            f"{owner}/{repo}: alias '{alias}'(기대 '{exp_alias}') 불일치 — "
                            f"write 가능(collaborator?) 또는 권한 확인 불가; 의도 확인 권고"
                        ),
                        location=project_dir,
                    )
                )
        return results
