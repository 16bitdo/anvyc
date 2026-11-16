"""`.git/config` 의 remote URL → owner/repo/ssh_alias 추출 (P4, v0.8.0).

지원 URL 형식:
- [<user>@]<host>:<owner>/<repo>(.git)?       ← SSH scp 형식 (ssh alias 패턴 'github.com-<alias>' 포함)
- https://<host>/<owner>/<repo>(.git)?/?       ← HTTPS

다른 hoster (gitlab.com, bitbucket.org, ...) 도 동일 패턴이라 host 그대로 보존.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# git 의 scp 형식은 `[user@]host:path`(git-clone(1) "GIT URLS") — 사용자 부분은 생략할 수 있고
# `git` 으로 정해져 있지도 않다(`git@` 를 필수로 두면 사용자 생략 원격을 통째로 잃는다).
# 첫 콜론 앞에 슬래시가 있으면 git 은 로컬 경로로 보므로 host 에 `/` 를 허용하지 않는다.
_SSH_RE = re.compile(
    r"^(?:[^@/:]+@)?(?P<host>[^@/:]+):(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$"
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


def _resolve_gitdir_pointer(dotgit_file: Path) -> Path | None:
    """`.git` 파일(`gitdir: <path>` 포인터) → remote config 를 읽을 git 디렉터리.

    linked worktree 의 `.git` 은 디렉터리가 아니라 이 포인터 파일이다(실측:
    `git worktree add` 로 만든 worktree, 2026-08-13). 포인터가 가리키는 디렉터리는
    보통 worktree 전용 사설 gitdir(`<본체>/.git/worktrees/<name>/`)이고, 그 안의
    `commondir` 파일이 remote 설정을 가진 공통 `.git` 디렉터리(본체)를 상대경로로
    가리킨다. `commondir` 이 없으면(예: `.git` 파일 포맷을 공유하는 git submodule
    처럼 포인터 대상 자체가 이미 독립된 config 를 가짐) 포인터가 가리키는 디렉터리를
    그대로 쓴다.

    포인터·commondir 값은 로컬 git 이 쓴 파일이지만 신뢰하지 않는다 — 상대경로는
    각자의 기준 디렉터리(포인터는 이 `.git` 파일의 부모, commondir 은 포인터가
    가리키는 디렉터리)를 기준으로 pathlib `/` 연산만으로 해석한다(prefix 를 잘라내는
    문자열 슬라이싱은 쓰지 않는다 — sync.py 의 path-traversal 회귀 참조). 값이
    `..`/절대경로를 포함해도 별도로 막지 않는다 — 원격 입력이 아니라 로컬 git 이
    쓴 파일이고, 실패해도 아래에서 읽기 전용으로만 쓰인다.

    어느 단계든 실패하면(파일 없음/권한 오류/형식 불일치) 예외를 던지지 않고
    `None` 을 반환한다 — 호출부(`anvyc doctor`·`anvyc gh`)는 offline·non-fatal
    경로라 여기서 죽으면 안 된다. `commondir` 부재는 실패가 아니라 정상 분기다.

    linked worktree 레이아웃으로만 검증했다 — submodule 의 `.git` 파일도 동일
    포인터 형식을 쓰지만 별도로 테스트하지는 않았다. (2026-11-16 `project_info`
    에서 옮겼다 — 그곳에만 있어 다른 호출부는 worktree 를 읽지 못했다.)
    """
    try:
        raw = dotgit_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    stripped = raw.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0]
    if not first_line.startswith("gitdir:"):
        return None
    pointer = first_line[len("gitdir:"):].strip()
    if not pointer:
        return None

    try:
        pointer_path = Path(pointer)
    except ValueError:
        return None
    git_dir = pointer_path if pointer_path.is_absolute() else dotgit_file.parent / pointer_path

    commondir_file = git_dir / "commondir"
    try:
        commondir_exists = commondir_file.is_file()
    except OSError:
        return None
    if not commondir_exists:
        return git_dir  # 비-worktree gitdir(예: submodule) — 포인터 대상을 그대로 사용

    try:
        common_raw = commondir_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not common_raw:
        return None
    common_first_line = common_raw.splitlines()[0]

    try:
        common_path = Path(common_first_line)
    except ValueError:
        return None
    return common_path if common_path.is_absolute() else git_dir / common_path


def parse_git_config(git_dir: Path) -> list[GitRemoteInfo]:
    """`<project>/.git` 의 config 에서 [remote "X"] section 들을 파싱.

    `git_dir` 은 `.git` 디렉터리이거나 linked worktree·submodule 의 `.git` 포인터
    파일(`gitdir: <path>`)이다 — 파일이면 공통 git 디렉터리까지 따라가 그 config 를
    읽는다. 호출부마다 `.git` 을 디렉터리로 가정해 worktree 에서 원격을 잃었다
    (2026-11-16 — `anvyc gh` 가 worktree 에서 계정 도출에 실패).

    configparser 를 쓰지 않는다. git config 는 INI 가 아니라서(같은 키의 다중값,
    `=` 없는 boolean 키) 엄격 INI 파서가 예외를 던졌고, 그 예외 하나에 원격 전체를
    잃었다(2026-11-12 — `anvyc gh` 가 계정 도출에 실패하고 doctor 는 저장소를 조용히
    건너뛰었다). 줄 단위로 읽어 이해하지 못하는 줄만 건너뛴다.
    """
    if git_dir.is_file():
        resolved = _resolve_gitdir_pointer(git_dir)
        if resolved is None:
            return []
        git_dir = resolved
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
