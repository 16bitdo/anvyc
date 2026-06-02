"""`anvyc gh` — race-immune gh account 라우팅.

cwd repo 의 origin remote SSH alias(github.com-<account>)가 인코딩한 account 의 토큰을
`gh auth token --user` 로 추출해 GH_TOKEN env 로 주입하여 gh 를 실행한다. 전역 active
account 를 건드리지 않아 동시 세션 race 면역.
spec: docs/superpowers/specs/2026-06-02-anvyc-gh-routing-design.md
"""
from __future__ import annotations

from pathlib import Path

from anvyc.utils.git_remote import parse_git_config


class GhRouteError(RuntimeError):
    """account 도출 불가 / 토큰 취득 실패 / gh 미설치 — 비0 exit 로 변환."""


def resolve_account(start: Path) -> str | None:
    """start 에서 .git 디렉터리를 상위로 탐색 → origin remote 의 ssh_alias(=account).

    origin 없음 / alias 없는 plain remote / .git 없음 → None.
    """
    cur = Path(start).resolve()
    for d in (cur, *cur.parents):
        git_dir = d / ".git"
        if git_dir.is_dir():
            for remote in parse_git_config(git_dir):
                if remote.name == "origin":
                    return remote.ssh_alias
            return None
    return None
