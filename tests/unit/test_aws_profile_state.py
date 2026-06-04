"""core/aws_profile_state — 인증 방식 탐지 + profile 상태 판정."""
from anvyc.core.aws_profile_state import (
    AUTH_ASSUME_ROLE,
    AUTH_CREDENTIAL_PROCESS,
    AUTH_INCOMPLETE,
    AUTH_SSO,
    AUTH_STATIC,
    AUTH_STATIC_TEMP,
    AUTH_WEB_IDENTITY,
    detect_auth_method,
)


def test_detect_sso() -> None:
    assert detect_auth_method({"sso_session": "ws"}, has_static=False) == AUTH_SSO
    assert detect_auth_method({"sso_start_url": "u"}, has_static=False) == AUTH_SSO


def test_detect_assume_role() -> None:
    keys = {"role_arn": "arn:...", "source_profile": "base"}
    assert detect_auth_method(keys, has_static=False) == AUTH_ASSUME_ROLE


def test_detect_credential_process() -> None:
    assert detect_auth_method({"credential_process": "aws-vault exec x"}, has_static=False) == AUTH_CREDENTIAL_PROCESS


def test_detect_web_identity() -> None:
    assert detect_auth_method({"web_identity_token_file": "/t"}, has_static=False) == AUTH_WEB_IDENTITY


def test_detect_static_and_temp() -> None:
    assert detect_auth_method({}, has_static=True) == AUTH_STATIC
    assert detect_auth_method({"aws_session_token": "x"}, has_static=True) == AUTH_STATIC_TEMP


def test_detect_incomplete() -> None:
    assert detect_auth_method({"region": "us-east-1"}, has_static=False) == AUTH_INCOMPLETE


def test_detect_precedence_sso_over_static() -> None:
    # sso_session + 정적 키가 공존해도 SSO 우선.
    assert detect_auth_method({"sso_session": "ws"}, has_static=True) == AUTH_SSO
