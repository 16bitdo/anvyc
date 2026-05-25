"""Unit tests for anvyc.checks.creds_expiry (CP-5 2/3)."""
from __future__ import annotations

from unittest.mock import patch

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.creds_expiry import (
    CHECK_NAME,
    THRESHOLD_DAYS,
    CredsExpiryWithin7dCheck,
)
from anvyc.core.creds import (
    STATUS_EXPIRED,
    STATUS_EXPIRING,
    STATUS_UNKNOWN,
    STATUS_VALID,
    CredentialsReport,
    CredentialStatus,
)


def _make_report(creds: list[CredentialStatus]) -> CredentialsReport:
    return CredentialsReport(
        schema_version=1,
        generated_at="2026-05-25T00:00:00Z",
        warn_threshold_days=THRESHOLD_DAYS,
        credentials=creds,
    )


def _cred(*, kind: str = "aws_sso", identifier: str = "x", status: str, expires_at: str | None = None, sec: int | None = None) -> CredentialStatus:
    return CredentialStatus(
        kind=kind,
        identifier=identifier,
        source="/test",
        expires_at=expires_at,
        expires_in_seconds=sec,
        status=status,
    )


def test_check_name_and_threshold() -> None:
    assert CHECK_NAME == "creds-expiry-within-7d"
    assert THRESHOLD_DAYS == 7
    assert CredsExpiryWithin7dCheck.name == CHECK_NAME


def test_check_empty_no_credentials() -> None:
    """no credentials → no results."""
    check = CredsExpiryWithin7dCheck()
    with patch("anvyc.checks.creds_expiry.collect_credentials", return_value=_make_report([])):
        results = check.run(CheckContext())
    assert results == []


def test_check_silent_on_valid_and_unknown() -> None:
    """valid / unknown 만 있으면 result 없음."""
    creds = [
        _cred(status=STATUS_VALID, identifier="aws-prod", sec=30 * 86400),
        _cred(kind="claude_oauth", status=STATUS_VALID, identifier="x@y.com"),
        _cred(kind="github", status=STATUS_UNKNOWN, identifier="github.com/u"),
    ]
    check = CredsExpiryWithin7dCheck()
    with patch("anvyc.checks.creds_expiry.collect_credentials", return_value=_make_report(creds)):
        results = check.run(CheckContext())
    assert results == []


def test_check_critical_on_expired() -> None:
    creds = [
        _cred(status=STATUS_EXPIRED, identifier="aws-prod", expires_at="2026-05-10T15:13:20Z", sec=-86400 * 15),
    ]
    check = CredsExpiryWithin7dCheck()
    with patch("anvyc.checks.creds_expiry.collect_credentials", return_value=_make_report(creds)):
        results = check.run(CheckContext())
    assert len(results) == 1
    r = results[0]
    assert r.check_name == CHECK_NAME
    assert r.severity == Severity.CRITICAL
    assert "expired" in r.message
    assert "aws-prod" in r.message
    assert "2026-05-10T15:13:20Z" in r.message
    assert r.suggestion is not None
    assert "aws sso login" in r.suggestion


def test_check_warning_on_expiring() -> None:
    creds = [
        _cred(
            kind="github",
            status=STATUS_EXPIRING,
            identifier="github.com/alice",
            expires_at="2026-05-30T00:00:00Z",
            sec=3 * 86400,
        ),
    ]
    check = CredsExpiryWithin7dCheck()
    with patch("anvyc.checks.creds_expiry.collect_credentials", return_value=_make_report(creds)):
        results = check.run(CheckContext())
    assert len(results) == 1
    r = results[0]
    assert r.severity == Severity.WARNING
    assert "expires soon" in r.message
    assert "github.com/alice" in r.message
    assert "3d 남음" in r.message


def test_check_mixed_status_returns_only_blocking() -> None:
    """mixed pool — expired + expiring 만 result. valid/unknown skip."""
    creds = [
        _cred(status=STATUS_EXPIRED, identifier="aws-1", sec=-86400),
        _cred(status=STATUS_EXPIRING, identifier="aws-2", sec=2 * 86400),
        _cred(status=STATUS_VALID, identifier="aws-3", sec=30 * 86400),
        _cred(kind="claude_oauth", status=STATUS_UNKNOWN, identifier="x@y.com"),
        _cred(kind="github", status=STATUS_EXPIRED, identifier="github.com/u", sec=-3600),
    ]
    check = CredsExpiryWithin7dCheck()
    with patch("anvyc.checks.creds_expiry.collect_credentials", return_value=_make_report(creds)):
        results = check.run(CheckContext())
    assert len(results) == 3
    severities = [r.severity for r in results]
    assert severities.count(Severity.CRITICAL) == 2
    assert severities.count(Severity.WARNING) == 1


def test_check_calls_collect_with_no_github_probe() -> None:
    """doctor 의 read-only 원칙 — collect_credentials 호출 시 probe_github_expiry=False."""
    check = CredsExpiryWithin7dCheck()
    with patch("anvyc.checks.creds_expiry.collect_credentials", return_value=_make_report([])) as mock_collect:
        check.run(CheckContext())
    mock_collect.assert_called_once_with(
        warn_threshold_days=THRESHOLD_DAYS,
        probe_github_expiry=False,
    )


def test_check_registered_in_doctor() -> None:
    """doctor._REGISTRY 에 creds-expiry-within-7d 등록 확인."""
    from anvyc.core.doctor import _REGISTRY
    assert CHECK_NAME in _REGISTRY
    assert _REGISTRY[CHECK_NAME].name == CHECK_NAME
