"""~/.aws/config 의 profile 이름 추출 (shared by checks/project_aws_profile, multi_account_detected).

`[default]` 와 `[profile X]` section 만 인식. `[sso-session *]` 같은 다른 section 은 제외.
"""
from __future__ import annotations

import configparser
from pathlib import Path

DEFAULT_AWS_CONFIG = Path("~/.aws/config").expanduser()

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
