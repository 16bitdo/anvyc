"""`.git/config` 의 remote URL → owner/repo/ssh_alias 추출 (P4, v0.8.0).

지원 URL 형식:
- git@<host>:<owner>/<repo>(.git)?            ← SSH (ssh alias 패턴 'github.com-<alias>' 포함)
- https://<host>/<owner>/<repo>(.git)?/?       ← HTTPS

다른 hoster (gitlab.com, bitbucket.org, ...) 도 동일 패턴이라 host 그대로 보존.
"""
from __future__ import annotations

import configparser
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


def parse_git_config(git_dir: Path) -> list[GitRemoteInfo]:
    """`<project>/.git/config` 의 [remote "X"] section 들을 파싱."""
    config_path = git_dir / "config"
    if not config_path.is_file():
        return []
    cp = configparser.RawConfigParser()
    try:
        cp.read(config_path, encoding="utf-8")
    except (OSError, configparser.Error):
        return []
    out: list[GitRemoteInfo] = []
    for section in cp.sections():
        if not (section.startswith('remote "') and section.endswith('"')):
            continue
        name = section[len('remote "'):-1].strip()
        if not name:
            continue
        url = cp.get(section, "url", fallback="")
        info = _parse_url(name, url)
        if info:
            out.append(info)
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
