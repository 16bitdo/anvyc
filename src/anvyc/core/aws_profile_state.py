"""AWS profile 인증 방식 + 연결 상태 판정 (읽기 전용, **네트워크 의존 0**).

doctor / project doctor / `aws profile` 가 공유하는 순수 코어. SSO 캐시 파싱은
`core/creds.py:detect_aws_sso` 를 재사용한다. 네트워크 liveness probe 는
`core/aws_probe.py` 로 분리(이 모듈은 import 하지 않음) → doctor 가 구조적으로 offline.
"""
from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from anvyc.checks.base import CheckResult, Severity  # noqa: F401
from anvyc.core.creds import (
    AWS_SSO_WARN_DAYS,
    STATUS_EXPIRED,  # noqa: F401
    STATUS_EXPIRING,  # noqa: F401
    STATUS_UNKNOWN,
    STATUS_VALID,  # noqa: F401
    detect_aws_sso,
)
from anvyc.utils.aws_config import (
    load_aws_profile_names,
    load_credentials_profile_names,
    load_profile_config,
    load_profile_sso_meta,
)

AUTH_UNDEFINED = "undefined"
AUTH_SSO = "sso"
AUTH_STATIC = "static"
AUTH_STATIC_TEMP = "static_temporary"
AUTH_ASSUME_ROLE = "assume_role"
AUTH_CREDENTIAL_PROCESS = "credential_process"
AUTH_WEB_IDENTITY = "web_identity"
AUTH_INCOMPLETE = "incomplete"

TOKEN_NONE = "none"  # SSO profile 인데 캐시 토큰 없음(미로그인)


@dataclass
class AwsProfileState:
    profile: str
    defined: bool
    auth_method: str = AUTH_UNDEFINED
    status: str = ""
    sso_session: str | None = None
    expires_at: str | None = None
    expires_in_seconds: int | None = None
    source_profile: str | None = None
    credential_process_cmd: str | None = None
    token_file_exists: bool | None = None


def detect_auth_method(keys: dict[str, str], *, has_static: bool) -> str:
    """profile 섹션 키 + 정적 자격 존재 여부로 인증 방식 분류 (AWS SDK 해석 우선순위 정합)."""
    if "sso_session" in keys or "sso_start_url" in keys:
        return AUTH_SSO
    if "role_arn" in keys and ("source_profile" in keys or "credential_source" in keys):
        return AUTH_ASSUME_ROLE
    if "credential_process" in keys:
        return AUTH_CREDENTIAL_PROCESS
    if "web_identity_token_file" in keys:
        return AUTH_WEB_IDENTITY
    if has_static or "aws_access_key_id" in keys:
        return AUTH_STATIC_TEMP if "aws_session_token" in keys else AUTH_STATIC
    return AUTH_INCOMPLETE


def evaluate_profile_state(
    profile: str, *, home: Path | None = None, now: datetime | None = None
) -> AwsProfileState:
    """profile 의 인증 방식과 오프라인 상태를 판정한다 (네트워크 호출 없음)."""
    home = home or Path.home()
    now = now or datetime.now(UTC)
    config_path = home / ".aws" / "config"
    creds_path = home / ".aws" / "credentials"

    if profile not in load_aws_profile_names(config_path):
        return AwsProfileState(profile=profile, defined=False, auth_method=AUTH_UNDEFINED, status="missing")

    keys = load_profile_config(profile, config_path) or {}
    has_static = (profile in load_credentials_profile_names(creds_path)) or ("aws_access_key_id" in keys)
    method = detect_auth_method(keys, has_static=has_static)
    st = AwsProfileState(profile=profile, defined=True, auth_method=method)

    if method == AUTH_SSO:
        meta = load_profile_sso_meta(profile, config_path) or (None, None)
        st.sso_session, start_url = meta
        if not start_url:
            st.status = STATUS_UNKNOWN
            return st
        by_url = {
            c.identifier: c
            for c in detect_aws_sso(home, warn_threshold_days=AWS_SSO_WARN_DAYS, now=now)
        }
        cred = by_url.get(start_url)
        if cred is None:
            st.status = TOKEN_NONE
        else:
            st.status = cred.status
            st.expires_at = cred.expires_at
            st.expires_in_seconds = cred.expires_in_seconds
        return st

    if method == AUTH_ASSUME_ROLE:
        src = keys.get("source_profile")
        if src:
            st.source_profile = src
            st.status = "source_ok" if src in load_aws_profile_names(config_path) else "source_missing"
        else:
            st.status = "env"
        return st

    if method == AUTH_CREDENTIAL_PROCESS:
        cmd = keys.get("credential_process", "")
        st.credential_process_cmd = cmd
        first = shlex.split(cmd)[0] if cmd.strip() else ""
        st.status = "cmd_ok" if (first and shutil.which(first)) else "cmd_missing"
        return st

    if method == AUTH_WEB_IDENTITY:
        tf = keys.get("web_identity_token_file", "")
        st.token_file_exists = bool(tf) and Path(tf).expanduser().is_file()
        st.status = "classified"
        return st

    if method in (AUTH_STATIC, AUTH_STATIC_TEMP):
        st.status = "present"
        return st

    st.status = "incomplete"
    return st
