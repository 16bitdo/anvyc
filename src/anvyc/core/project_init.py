"""anvyc project init — per-project gh 라우팅 `.envrc` 스캐폴딩 (순수 로직).

cli.py 의 `project init` 커맨드가 이 함수들을 오케스트레이션한다.
spec: docs/superpowers/specs/2026-06-05-project-init-gh-routing-design.md
"""
from __future__ import annotations

import re
from pathlib import Path

from anvyc.core import gh_route
from anvyc.core.project_info import gh_config_dir_for_account
from anvyc.utils.git_remote import parse_git_config

_GH_LINE_RE = re.compile(r"^[ \t]*export[ \t]+GH_CONFIG_DIR[ \t]*=.*$", re.MULTILINE)


def write_envrc_gh_routing(envrc: Path, account: str) -> str:
    """`.envrc` 에 GH_CONFIG_DIR export 줄을 멱등 주입.

    반환: "created"(파일 신규) / "added"(기존 파일에 줄 추가) /
          "replaced"(기존 GH_CONFIG_DIR 줄 교체) / "unchanged"(이미 동일).
    기존 다른 export 는 보존한다.
    """
    line = f'export GH_CONFIG_DIR="{gh_config_dir_for_account(account)}"'
    if not envrc.exists():
        envrc.write_text(line + "\n", encoding="utf-8")
        return "created"
    text = envrc.read_text(encoding="utf-8")
    m = _GH_LINE_RE.search(text)
    if m:
        if m.group(0).strip() == line:
            return "unchanged"
        new_text = _GH_LINE_RE.sub(line, text, count=1)
        if not new_text.endswith("\n"):
            new_text += "\n"
        envrc.write_text(new_text, encoding="utf-8")
        return "replaced"
    sep = "" if text == "" or text.endswith("\n") else "\n"
    envrc.write_text(text + sep + line + "\n", encoding="utf-8")
    return "added"


def ensure_gitignore_entry(gitignore: Path, entry: str) -> bool:
    """`.gitignore` 에 `entry` 줄이 없으면 추가. 변경 시 True, 이미 있으면 False.

    `.gitignore` 부재 시 생성. 비교는 줄 단위 strip 일치.
    """
    if gitignore.exists():
        text = gitignore.read_text(encoding="utf-8")
        if entry in (ln.strip() for ln in text.splitlines()):
            return False
        sep = "" if text == "" or text.endswith("\n") else "\n"
        gitignore.write_text(text + sep + entry + "\n", encoding="utf-8")
        return True
    gitignore.write_text(entry + "\n", encoding="utf-8")
    return True


def resolve_routing_account(
    path: Path, owner_accounts: dict[str, str]
) -> tuple[str | None, str]:
    """origin 으로부터 gh account 도출.

    1. origin ssh alias 있음 → (alias, "alias")  — `gh_route.resolve_account` 재사용
    2. alias 없음(plain host) → origin owner → `owner_accounts` 조회 → (account, "mapping")
    3. 도출 불가(remote 없음 / 매핑 없음) → (None, "unknown")

    `path` 는 repo 루트여야 한다 (호출부 cli `project init` 가 `path/.git` 존재 확인 후 호출).
    """
    alias = gh_route.resolve_account(path)
    if alias:
        return (alias, "alias")
    for remote in parse_git_config(path / ".git"):
        if remote.name == "origin":
            mapped = owner_accounts.get(remote.owner)
            if mapped:
                return (mapped, "mapping")
            break
    return (None, "unknown")


def gh_account_logged_in(account: str, config_home: Path | None = None) -> bool:
    """`<config_home>/gh-<account>/hosts.yml` 존재 여부 (= 해당 계정 로그인됨).

    `config_home` 기본 `$HOME/.config`. **내용은 보지 않고 존재만 stat** (토큰 미접근).
    """
    base = config_home or (Path.home() / ".config")
    return (base / f"gh-{account}" / "hosts.yml").is_file()
