"""gh CLI `hosts.yml` multi-config-dir walker (CP-13 PR-13D).

`~/.config/gh*` glob 으로 GH_CONFIG_DIR 분리 패턴 (CLAUDE.md / direnv 의
`export GH_CONFIG_DIR=...` 미러) 까지 모든 hosts.yml 을 발견. 각 hosts.yml
의 host / user 목록을 (config_dir, host, user) 튜플로 yield.

minimal YAML parser — PyYAML 미의존 (anvyc core dep 정책 §38.1 ¶6). gh CLI
의 `hosts.yml` 형식만 인식 (`<host>:\\n  users:\\n    <user>:\\n      ...`).

본 util 은 *read-only* — 어느 파일도 수정하지 않음. 호출자는 token 본문을
저장하지 않으며, billing API 호출 시 `GH_CONFIG_DIR` env 설정 후 gh CLI 가
keyring 에서 token 을 가져오도록 위임 (R3 정합 — costwatch 는 키 미보유).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_HOME = Path("~/.config").expanduser()
GH_CONFIG_GLOB = "gh*"


@dataclass(frozen=True)
class GhAccount:
    """단일 gh login 의 위치 정보.

    `config_dir` = `~/.config/gh*` 중 하나 (e.g. `~/.config/gh-16bitdo`).
    이 값을 `GH_CONFIG_DIR` env 로 설정하면 gh CLI 가 해당 계정 token 사용.
    """

    config_dir: Path
    host: str
    user: str


def parse_hosts_yml(hosts_yml: Path) -> dict[str, list[str]]:
    """단일 hosts.yml → `{host: [users]}` dict.

    파일 부재 / 파싱 실패 시 빈 dict (graceful). gh CLI 의 `hosts.yml`
    형식만 인식 (indent flexible — gh 1.x 의 2-space 와 신버전의 4-space
    모두 처리). 다른 YAML 구조는 skip.

    인식 패턴 (indent N > 0):
        <host>:                      ← 0 indent
        <N space>users:              ← N indent
        <M space><user>:             ← M > N indent
    """
    if not hosts_yml.is_file():
        return {}
    try:
        text = hosts_yml.read_text(encoding="utf-8")
    except OSError:
        return {}
    result: dict[str, list[str]] = {}
    current_host: str | None = None
    users_indent: int | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # host 라인 (0 indent)
        m_host = re.match(r"^([A-Za-z0-9._-]+):\s*$", line)
        if m_host and not line.startswith(" ") and not line.startswith("\t"):
            current_host = m_host.group(1)
            result[current_host] = []
            users_indent = None
            continue
        if current_host is None:
            continue
        # users: 라인 — indent 동적 캡쳐
        m_users = re.match(r"^(\s+)users:\s*$", line)
        if m_users:
            users_indent = len(m_users.group(1))
            continue
        # user entry — users_indent 보다 더 깊은 indent
        if users_indent is not None:
            m_user = re.match(r"^(\s+)([A-Za-z0-9._-]+):\s*$", line)
            if m_user:
                indent = len(m_user.group(1))
                if indent > users_indent:
                    result[current_host].append(m_user.group(2))
                    continue
                # indent 가 users_indent 와 동일/낮음 → users block 이탈
                users_indent = None
            else:
                # user entry 아닌 다른 line — indent 비교로 block 이탈 판단
                stripped_indent = len(line) - len(line.lstrip())
                if stripped_indent <= users_indent:
                    users_indent = None
    return result


def discover_gh_config_dirs(config_home: Path | None = None) -> list[Path]:
    """`~/.config/gh*` glob 으로 모든 GH_CONFIG_DIR 후보 디렉터리 반환.

    `~/.config/gh` (default), `~/.config/gh-16bitdo`, `~/.config/gh-heisgone`
    등. dir 만 반환 — 파일은 skip. 정렬 순서 = path 사전식.
    """
    home = config_home or DEFAULT_CONFIG_HOME
    if not home.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(home.glob(GH_CONFIG_GLOB)):
        if entry.is_dir():
            out.append(entry)
    return out


def discover_gh_accounts(config_home: Path | None = None) -> list[GhAccount]:
    """모든 `~/.config/gh*` dir 의 hosts.yml 을 walk 해 GhAccount 목록 반환.

    (config_dir, host, user) 의 중복은 보존 — 동일 계정이 여러 dir 에서
    탐지되면 각 dir 별 entry 가 생성. 호출자가 정책 적용 (e.g.,
    `~/.config/gh-<user>` 우선).
    """
    out: list[GhAccount] = []
    for cfg_dir in discover_gh_config_dirs(config_home):
        hosts_yml = cfg_dir / "hosts.yml"
        for host, users in parse_hosts_yml(hosts_yml).items():
            for user in users:
                out.append(
                    GhAccount(config_dir=cfg_dir, host=host, user=user)
                )
    return out


def select_config_dir_for_user(
    user: str, *, config_home: Path | None = None
) -> Path | None:
    """단일 user 에 대해 가장 적절한 `GH_CONFIG_DIR` 1개 선택.

    선호 순서:
      1. `~/.config/gh-<user>` (명시 분리 — direnv 패턴 미러)
      2. user 가 등장하는 첫 번째 dir (사전식)
      3. 없으면 `None`

    호출자는 본 경로를 `GH_CONFIG_DIR` env 에 설정한 뒤 `gh api ...` 호출.
    """
    home = config_home or DEFAULT_CONFIG_HOME
    preferred = home / f"gh-{user}"
    accounts = discover_gh_accounts(home)
    # 1) 명시 분리 dir 우선
    for acct in accounts:
        if acct.user == user and acct.config_dir == preferred:
            return acct.config_dir
    # 2) 첫 번째 dir
    for acct in accounts:
        if acct.user == user:
            return acct.config_dir
    return None


__all__ = [
    "DEFAULT_CONFIG_HOME",
    "GhAccount",
    "discover_gh_accounts",
    "discover_gh_config_dirs",
    "parse_hosts_yml",
    "select_config_dir_for_user",
]
