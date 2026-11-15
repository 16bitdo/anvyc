"""`.git/config` 의 remote URL → owner/repo/ssh_alias 추출 (P4, v0.8.0).

지원 URL 형식:
- git@<host>:<owner>/<repo>(.git)?            ← SSH (ssh alias 패턴 'github.com-<alias>' 포함)
- https://<host>/<owner>/<repo>(.git)?/?       ← HTTPS

다른 hoster (gitlab.com, bitbucket.org, ...) 도 동일 패턴이라 host 그대로 보존.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SSH_RE = re.compile(
    r"^git@(?P<host>[^:]+):(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$"
)
_HTTPS_RE = re.compile(
    r"^https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?/?$"
)

# git config 문법(git-config(1) "Syntax") 중 원격 URL 을 읽는 데 필요한 부분.
# `[section]` · `[section "subsection"]` · 구식 `[section.subsection]` 헤더, 그 뒤의
# `key = value` 줄. 섹션·키 이름은 대소문자를 가리지 않고 서브섹션은 가린다.
_SECTION_RE = re.compile(r'^\[\s*([A-Za-z0-9.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\](.*)$')
_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)\s*(?:=(.*))?$")


@dataclass
class GitRemoteInfo:
    name: str            # "origin", "upstream", ...
    url: str
    host: str            # "github.com", "github.com-<alias>", "gitlab.com", ...
    owner: str
    repo: str
    ssh_alias: str | None  # github.com-<alias> 의 alias suffix (없으면 None)
    protocol: str        # "ssh" | "https"


def _parse_url(name: str, url: str) -> GitRemoteInfo | None:
    m = _SSH_RE.match(url)
    if m:
        host = m.group("host")
        alias: str | None = None
        if host.startswith("github.com-"):
            alias = host[len("github.com-"):]
        return GitRemoteInfo(
            name=name,
            url=url,
            host=host,
            owner=m.group("owner"),
            repo=m.group("repo"),
            ssh_alias=alias,
            protocol="ssh",
        )
    m = _HTTPS_RE.match(url)
    if m:
        return GitRemoteInfo(
            name=name,
            url=url,
            host=m.group("host"),
            owner=m.group("owner"),
            repo=m.group("repo"),
            ssh_alias=None,
            protocol="https",
        )
    return None


def _config_value(raw: str) -> str:
    """git config 값 — 따옴표를 벗기고 이스케이프를 풀며, 따옴표 밖 `#`·`;` 부터는 주석."""
    out: list[str] = []
    quoted = False
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == '"':
            quoted = not quoted
        elif c in "#;" and not quoted:
            break
        elif c == "\\" and i + 1 < len(raw):
            i += 1
            out.append({"n": "\n", "t": "\t", "b": "\b"}.get(raw[i], raw[i]))
        else:
            out.append(c)
        i += 1
    return "".join(out).strip()


def _remote_urls(text: str) -> dict[str, str]:
    """remote 이름 → url. 같은 remote 에 url 이 여럿이면 **첫 값**이 이긴다.

    `git remote get-url` 과 fetch 가 쓰는 값이 첫 값이다. `git config --get` 은
    마지막 값을 돌려주므로 그 의미를 흉내 내면 push 미러를 잡는다.
    """
    urls: dict[str, str] = {}
    remote: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        header = _SECTION_RE.match(line)
        if header:
            section, sub, line = header.group(1).lower(), header.group(2), header.group(3).strip()
            if sub is None and "." in section:  # 구식 `[remote.origin]` 표기
                section, _, sub = section.partition(".")
            remote = re.sub(r"\\(.)", r"\1", sub) if section == "remote" and sub else None
        if remote is None or not line or line[0] in "#;":
            continue
        kv = _KEY_RE.match(line)
        if kv and kv.group(1).lower() == "url" and kv.group(2) is not None:
            urls.setdefault(remote, _config_value(kv.group(2)))
    return urls


def parse_git_config(git_dir: Path) -> list[GitRemoteInfo]:
    """`<project>/.git/config` 의 [remote "X"] section 들을 파싱.

    configparser 를 쓰지 않는다. git config 는 INI 가 아니라서(같은 키의 다중값,
    `=` 없는 boolean 키) 엄격 INI 파서가 예외를 던졌고, 그 예외 하나에 원격 전체를
    잃었다(2026-11-12 — `anvyc gh` 가 계정 도출에 실패하고 doctor 는 저장소를 조용히
    건너뛰었다). 줄 단위로 읽어 이해하지 못하는 줄만 건너뛴다.
    """
    try:
        text = (git_dir / "config").read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    out = [info for name, url in _remote_urls(text).items() if (info := _parse_url(name, url))]
    return sorted(out, key=lambda r: r.name)


def to_dict(info: GitRemoteInfo) -> dict[str, Any]:
    return {
        "name": info.name,
        "url": info.url,
        "host": info.host,
        "owner": info.owner,
        "repo": info.repo,
        "ssh_alias": info.ssh_alias,
        "protocol": info.protocol,
    }


def origin_owner_repo(repo_dir: Path) -> tuple[str, str] | None:
    """origin remote 의 (owner, repo). origin 없음/파싱 실패 → None."""
    for remote in parse_git_config(repo_dir / ".git"):
        if remote.name == "origin":
            if remote.owner and remote.repo:
                return (remote.owner, remote.repo)
            return None
    return None
