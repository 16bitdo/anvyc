"""AWS profile 인증 방식 + 연결 상태 판정 (읽기 전용, **네트워크 의존 0**).

doctor / project doctor / `aws profile` 가 공유하는 순수 코어. SSO 캐시 파싱은
`core/creds.py:detect_aws_sso` 를 재사용한다. 네트워크 liveness probe 는
`core/aws_probe.py` 로 분리(이 모듈은 import 하지 않음) → doctor 가 구조적으로 offline.
"""
from __future__ import annotations

import shlex  # noqa: F401
import shutil  # noqa: F401
from dataclasses import dataclass
from datetime import UTC, datetime  # noqa: F401
from pathlib import Path  # noqa: F401

from anvyc.checks.base import CheckResult, Severity  # noqa: F401
from anvyc.core.creds import (
    AWS_SSO_WARN_DAYS,  # noqa: F401
    STATUS_EXPIRED,  # noqa: F401
    STATUS_EXPIRING,  # noqa: F401
    STATUS_UNKNOWN,  # noqa: F401
    STATUS_VALID,  # noqa: F401
    detect_aws_sso,  # noqa: F401
)
from anvyc.utils.aws_config import (
    load_aws_profile_names,  # noqa: F401
    load_credentials_profile_names,  # noqa: F401
    load_profile_config,  # noqa: F401
    load_profile_sso_meta,  # noqa: F401
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
