"""~/.aws/config 의 profile 이름 추출 (shared by checks/project_aws_profile, multi_account_detected).

`[default]` 와 `[profile X]` section 만 인식. `[sso-session *]` 같은 다른 section 은 제외.
"""
from __future__ import annotations

import configparser
from pathlib import Path

DEFAULT_AWS_CONFIG = Path("~/.aws/config").expanduser()
DEFAULT_AWS_CREDENTIALS = Path("~/.aws/credentials").expanduser()

_PROFILE_PREFIX = "profile "


def load_aws_profile_names(path: Path | None = None) -> set[str]:
    """`[profile X]` → 'X', `[default]` → 'default'. 파일 부재/파싱 실패 시 빈 set."""
    target = path or DEFAULT_AWS_CONFIG
    if not target.is_file():
        return set()
    cp = configparser.RawConfigParser()
    try:
        cp.read(target, encoding="utf-8")
    except (OSError, configparser.Error):
        return set()
    out: set[str] = set()
    for section in cp.sections():
        if section.startswith(_PROFILE_PREFIX):
            name = section[len(_PROFILE_PREFIX):].strip()
            if name:
                out.add(name)
    if cp.has_section("default"):
        out.add("default")
    return out


_SSO_SESSION_PREFIX = "sso-session "


def load_aws_sso_index(
    path: Path | None = None,
) -> dict[str, tuple[str | None, list[str]]]:
    """startUrl → (sso_session 이름, [profile 이름들]) 역매핑.

    신형: `[sso-session S]` sso_start_url=U + `[profile P]` sso_session=S → U:(S,[P...]).
    구형: `[profile P]` sso_start_url=U 직접 → U:(None,[P...]).
    profiles 는 정렬. 파일 부재/파싱 실패 → {}. (doctor 메시지에 어느 profile 인지 표시용.)
    """
    target = path or DEFAULT_AWS_CONFIG
    if not target.is_file():
        return {}
    cp = configparser.RawConfigParser()
    try:
        cp.read(target, encoding="utf-8")
    except (OSError, configparser.Error):
        return {}

    session_url: dict[str, str] = {}
    for section in cp.sections():
        if section.startswith(_SSO_SESSION_PREFIX):
            name = section[len(_SSO_SESSION_PREFIX):].strip()
            url = cp.get(section, "sso_start_url", fallback=None)
            if name and url:
                session_url[name] = url

    index: dict[str, tuple[str | None, list[str]]] = {}

    def _add(url: str, session: str | None, profile: str) -> None:
        if url not in index:
            index[url] = (session, [])
        index[url][1].append(profile)

    for section in cp.sections():
        if section == "default":
            profile = "default"
        elif section.startswith(_PROFILE_PREFIX):
            profile = section[len(_PROFILE_PREFIX):].strip()
        else:
            continue
        if not profile:
            continue
        session = cp.get(section, "sso_session", fallback=None)
        if session and session in session_url:
            _add(session_url[session], session, profile)
            continue
        direct = cp.get(section, "sso_start_url", fallback=None)
        if direct:
            _add(direct, None, profile)

    return {url: (session, sorted(profiles)) for url, (session, profiles) in index.items()}


def load_profile_config(profile: str, path: Path | None = None) -> dict[str, str] | None:
    """`[profile X]`(또는 `[default]`) 섹션의 key→value. profile 부재/파싱 실패 → None."""
    target = path or DEFAULT_AWS_CONFIG
    if not target.is_file():
        return None
    cp = configparser.RawConfigParser()
    try:
        cp.read(target, encoding="utf-8")
    except (OSError, configparser.Error):
        return None
    section = "default" if profile == "default" else f"{_PROFILE_PREFIX}{profile}"
    if not cp.has_section(section):
        return None
    return dict(cp.items(section))


def load_credentials_profile_names(path: Path | None = None) -> set[str]:
    """`~/.aws/credentials` 의 `[name]` 섹션 이름 집합. **값(시크릿)은 읽지 않음.**

    config 와 달리 섹션이 `[profilename]` (접두사 'profile ' 없음). 부재/파싱 실패 → 빈 set.
    """
    target = path or DEFAULT_AWS_CREDENTIALS
    if not target.is_file():
        return set()
    cp = configparser.RawConfigParser()
    try:
        cp.read(target, encoding="utf-8")
    except (OSError, configparser.Error):
        return set()
    return set(cp.sections())
