"""Unit tests for anvyc.checks.creds_expiry (CP-5 2/3)."""
from __future__ import annotations

from unittest.mock import patch

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.checks.creds_expiry import (
    CHECK_NAME,
    THRESHOLD_DAYS,
    CredsExpiryCheck,
)
from anvyc.core.creds import (
    DEFAULT_KIND_WARN_DAYS,
    KIND_AWS_SSO,
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
    assert CHECK_NAME == "creds-expiry"
    assert THRESHOLD_DAYS == 7
    assert CredsExpiryCheck.name == CHECK_NAME
    # aws_sso 는 per-kind override 로 15min (run-risk window — 영구 노이즈 회피).
    assert DEFAULT_KIND_WARN_DAYS[KIND_AWS_SSO] == 900 / 86400


def test_check_empty_no_credentials() -> None:
    """no credentials → no results."""
    check = CredsExpiryCheck()
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
    check = CredsExpiryCheck()
    with patch("anvyc.checks.creds_expiry.collect_credentials", return_value=_make_report(creds)):
        results = check.run(CheckContext())
    assert results == []


def test_check_critical_on_expired() -> None:
    creds = [
        _cred(status=STATUS_EXPIRED, identifier="aws-prod", expires_at="2026-05-10T15:13:20Z", sec=-86400 * 15),
    ]
    check = CredsExpiryCheck()
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
    check = CredsExpiryCheck()
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
    check = CredsExpiryCheck()
    with patch("anvyc.checks.creds_expiry.collect_credentials", return_value=_make_report(creds)):
        results = check.run(CheckContext())
    assert len(results) == 3
    severities = [r.severity for r in results]
    assert severities.count(Severity.CRITICAL) == 2
    assert severities.count(Severity.WARNING) == 1


def test_check_calls_collect_with_no_github_probe() -> None:
    """doctor 의 read-only 원칙 — collect_credentials 호출 시 probe_github_expiry=False."""
    check = CredsExpiryCheck()
    with patch("anvyc.checks.creds_expiry.collect_credentials", return_value=_make_report([])) as mock_collect:
        check.run(CheckContext())
    mock_collect.assert_called_once_with(
        warn_threshold_days=THRESHOLD_DAYS,
        kind_warn_days=DEFAULT_KIND_WARN_DAYS,
        probe_github_expiry=False,
    )


def test_check_uses_ctx_creds_warn_thresholds_override() -> None:
    """anvyc.yaml override(초)가 일 단위로 변환돼 코드 기본값 위에 merge 되어 전달."""
    ctx = CheckContext(creds_warn_thresholds={"aws_sso": 1800})  # 30min override
    check = CredsExpiryCheck()
    with patch(
        "anvyc.checks.creds_expiry.collect_credentials",
        return_value=_make_report([]),
    ) as mock_collect:
        check.run(ctx)
    kwargs = mock_collect.call_args.kwargs
    assert kwargs["kind_warn_days"]["aws_sso"] == 1800 / 86400  # override 적용(15min 기본 대체)
    assert kwargs["probe_github_expiry"] is False


def test_check_registered_in_doctor() -> None:
    """doctor._REGISTRY 에 creds-expiry 등록 확인."""
    from anvyc.core.doctor import _REGISTRY
    assert CHECK_NAME in _REGISTRY
    assert _REGISTRY[CHECK_NAME].name == CHECK_NAME


# ── project-scope (2026-05-31): aws_sso 자격을 "실행 중인 프로젝트" profile 로 한정 ──

def _aws_sso(*, profiles: tuple[str, ...], status: str = STATUS_EXPIRED, session: str = "aiforge") -> CredentialStatus:
    return CredentialStatus(
        kind="aws_sso",
        identifier="https://example.awsapps.com/start",
        source="/test",
        expires_at="2026-05-10T15:13:20Z",
        expires_in_seconds=-86400,
        status=status,
        profiles=profiles,
        sso_session=session,
    )


def _run(creds: list[CredentialStatus], ctx: CheckContext) -> list[CheckResult]:
    with patch("anvyc.checks.creds_expiry.collect_credentials", return_value=_make_report(creds)):
        return CredsExpiryCheck().run(ctx)


def test_scope_none_is_global() -> None:
    """scope=None(기본·비-doctor·테스트) → 전역, 기존 동작 유지 — aws_sso 보고."""
    creds = [_aws_sso(profiles=("audit", "dev", "prd"))]
    results = _run(creds, CheckContext())  # current_project_aws_profiles 기본 None
    assert len(results) == 1
    assert results[0].severity == Severity.CRITICAL


def test_scope_matching_profile_reports() -> None:
    """scope 에 자격 profile 과 교집합 → 보고 (해당 프로젝트가 그 SSO 를 씀)."""
    creds = [_aws_sso(profiles=("audit", "dev", "prd"))]
    ctx = CheckContext(current_project_aws_profiles=frozenset({"dev"}))
    results = _run(creds, ctx)
    assert len(results) == 1
    assert results[0].severity == Severity.CRITICAL


def test_scope_nonmatching_profile_silent() -> None:
    """scope 에 교집합 없음 → silent (프로젝트가 안 쓰는 SSO 만료는 안 보여줌)."""
    creds = [_aws_sso(profiles=("audit", "dev", "prd"))]
    ctx = CheckContext(current_project_aws_profiles=frozenset({"other-sso-profile"}))
    assert _run(creds, ctx) == []


def test_scope_empty_silences_all_aws_sso() -> None:
    """scope=frozenset()(프로젝트가 AWS profile 미사용, 예: 도구 repo) → 모든 aws_sso silent."""
    creds = [_aws_sso(profiles=("audit", "dev", "prd"))]
    ctx = CheckContext(current_project_aws_profiles=frozenset())
    assert _run(creds, ctx) == []


def test_scope_does_not_touch_non_aws_sso() -> None:
    """github/claude_oauth(profiles 빈 자격)은 scope 무관 — 항상 보고 (token 만료 억제 금지)."""
    creds = [
        _aws_sso(profiles=("audit",)),  # scope 와 교집합 없음 → skip
        _cred(kind="github", status=STATUS_EXPIRING, identifier="github.com/alice",
              expires_at="2026-05-30T00:00:00Z", sec=3 * 86400),
    ]
    ctx = CheckContext(current_project_aws_profiles=frozenset({"unrelated"}))
    results = _run(creds, ctx)
    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert "github" in results[0].message
