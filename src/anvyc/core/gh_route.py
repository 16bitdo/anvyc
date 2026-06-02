"""`anvyc gh` — race-immune gh account 라우팅.

cwd repo 의 origin remote SSH alias(github.com-<account>)가 인코딩한 account 의 토큰을
`gh auth token --user` 로 추출해 GH_TOKEN env 로 주입하여 gh 를 실행한다. 전역 active
account 를 건드리지 않아 동시 세션 race 면역.
spec: docs/superpowers/specs/2026-06-02-anvyc-gh-routing-design.md
"""
from __future__ import annotations

import os
import subprocess
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


def _token_for(account: str) -> str:
    """`gh auth token --user <account>` → 토큰 문자열. 실패 시 GhRouteError.

    토큰은 반환만 한다 — 절대 출력/로그하지 않는다.
    """
    try:
        cp = subprocess.run(
            ["gh", "auth", "token", "--user", account],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise GhRouteError("gh 가 설치되어 있지 않습니다.") from e
    if cp.returncode != 0 or not cp.stdout.strip():
        raise GhRouteError(
            f"account '{account}' 의 gh 토큰을 얻지 못했습니다 "
            f"(미인증? `gh auth login` 또는 `gh auth switch --user {account}` 로 추가)."
        )
    return cp.stdout.strip()


def run_gh(account: str, args: list[str]) -> int:
    """account 토큰을 GH_TOKEN 으로 주입하여 `gh <args>` 실행. gh 의 exit code 반환.

    child gh 는 stdin/stdout/stderr 를 상속(passthrough). 토큰은 env 로만 전달(argv 금지).
    """
    token = _token_for(account)
    env = dict(os.environ)
    env["GH_TOKEN"] = token
    try:
        cp = subprocess.run(["gh", *args], env=env)
    except FileNotFoundError as e:
        raise GhRouteError("gh 가 설치되어 있지 않습니다.") from e
    return cp.returncode
