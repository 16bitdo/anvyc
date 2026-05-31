"""cost-aws-explorer-iam doctor check 단위 테스트 (CP-13 PR-13C).

mock 전략 (PR-13C 결정 Q4=a): unittest.mock.patch 로 boto3 가용성과
sts/iam client 동작 교체.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.checks.cost_aws_explorer_iam import (
    CHECK_NAME,
    REQUIRED_ACTION,
    CostAwsExplorerIamCheck,
)


@pytest.fixture
def patched_aws_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """fake ~/.aws/config 경로 — load_aws_profile_names 가 본 경로 read."""
    cfg = tmp_path / "aws" / "config"
    monkeypatch.setattr("anvyc.utils.aws_config.DEFAULT_AWS_CONFIG", cfg)
    return cfg


def _write_aws_config(path: Path, profiles: list[str]) -> None:
    lines: list[str] = []
    for name in profiles:
        if name == "default":
            lines.append("[default]\nregion = us-east-1\n")
        else:
            lines.append(f"[profile {name}]\nregion = us-east-1\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def test_boto3_missing_yields_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """boto3 미설치 → WARNING + pip install 안내."""
    monkeypatch.setattr(
        "anvyc.checks.cost_aws_explorer_iam._boto3_available",
        lambda: False,
    )
    res = CostAwsExplorerIamCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert res[0].check_name == CHECK_NAME
    assert "boto3" in res[0].message
    assert res[0].suggestion is not None
    assert "anvyc[cost-aws]" in res[0].suggestion


def test_empty_aws_config_yields_silent(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """~/.aws/config 자체 부재 → silent (result 없음)."""
    monkeypatch.setattr(
        "anvyc.checks.cost_aws_explorer_iam._boto3_available",
        lambda: True,
    )
    # patched_aws_config 가 존재하지 않는 경로를 가리킴 (write 안 함)
    res = CostAwsExplorerIamCheck().run(CheckContext())
    assert res == []


def _make_session_with_allowed() -> MagicMock:
    """sts:GetCallerIdentity 성공 + iam:SimulatePrincipalPolicy allowed 반환."""
    sts = MagicMock()
    sts.get_caller_identity.return_value = {
        "Arn": "arn:aws:iam::123456789012:user/test"
    }
    iam = MagicMock()
    iam.simulate_principal_policy.return_value = {
        "EvaluationResults": [
            {"EvalActionName": REQUIRED_ACTION, "EvalDecision": "allowed"}
        ]
    }
    session_instance = MagicMock()
    session_instance.client.side_effect = (
        lambda name, **_: sts if name == "sts" else iam
    )
    return session_instance


def _fake_botocore_modules() -> MagicMock:
    """fake botocore + botocore.exceptions module with real Exception classes."""
    fake_botocore = MagicMock()
    fake_botocore.exceptions.ClientError = type(
        "FakeClientError", (Exception,), {}
    )
    fake_botocore.exceptions.BotoCoreError = type(
        "FakeBotoCoreError", (Exception,), {}
    )
    return fake_botocore


def test_allowed_yields_silent(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ce:GetCostAndUsage allowed → result 없음."""
    monkeypatch.setattr(
        "anvyc.checks.cost_aws_explorer_iam._boto3_available",
        lambda: True,
    )
    _write_aws_config(patched_aws_config, ["ws-dev"])

    fake_boto3 = MagicMock()
    fake_boto3.Session.return_value = _make_session_with_allowed()
    fake_botocore = _fake_botocore_modules()

    with patch.dict(
        "sys.modules",
        {
            "boto3": fake_boto3,
            "botocore": fake_botocore,
            "botocore.exceptions": fake_botocore.exceptions,
        },
    ):
        res = CostAwsExplorerIamCheck().run(CheckContext())
    assert res == []


def test_implicit_deny_yields_warning_with_template_path(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """implicitDeny → WARNING + IAM template 경로 안내."""
    monkeypatch.setattr(
        "anvyc.checks.cost_aws_explorer_iam._boto3_available",
        lambda: True,
    )
    _write_aws_config(patched_aws_config, ["ws-dev"])

    sts = MagicMock()
    sts.get_caller_identity.return_value = {
        "Arn": "arn:aws:iam::123456789012:user/test"
    }
    iam = MagicMock()
    iam.simulate_principal_policy.return_value = {
        "EvaluationResults": [
            {"EvalActionName": REQUIRED_ACTION, "EvalDecision": "implicitDeny"}
        ]
    }
    session_instance = MagicMock()
    session_instance.client.side_effect = (
        lambda name, **_: sts if name == "sts" else iam
    )

    fake_boto3 = MagicMock()
    fake_boto3.Session.return_value = session_instance
    fake_botocore = MagicMock()
    fake_botocore.exceptions.ClientError = type(
        "FakeClientError", (Exception,), {}
    )
    fake_botocore.exceptions.BotoCoreError = type(
        "FakeBotoCoreError", (Exception,), {}
    )

    with patch.dict(
        "sys.modules",
        {
            "boto3": fake_boto3,
            "botocore": fake_botocore,
            "botocore.exceptions": fake_botocore.exceptions,
        },
    ):
        res = CostAwsExplorerIamCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "ce:GetCostAndUsage" in res[0].message
    assert "implicitDeny" in res[0].message
    assert res[0].suggestion is not None
    assert "aws-cost-readonly.json" in res[0].suggestion


def test_sso_expired_yields_info(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sts 호출 시 SSO 만료 → INFO + aws sso login 안내."""
    monkeypatch.setattr(
        "anvyc.checks.cost_aws_explorer_iam._boto3_available",
        lambda: True,
    )
    _write_aws_config(patched_aws_config, ["ws-dev"])

    class FakeClientError(Exception):
        def __init__(self) -> None:
            super().__init__("SSO Token has expired")
            self.response = {"Error": {"Code": "ExpiredTokenException"}}

    class FakeBotoCoreError(Exception):
        pass

    sts = MagicMock()
    sts.get_caller_identity.side_effect = FakeClientError()
    session_instance = MagicMock()
    session_instance.client.return_value = sts

    fake_boto3 = MagicMock()
    fake_boto3.Session.return_value = session_instance
    fake_botocore = MagicMock()
    fake_botocore.exceptions.ClientError = FakeClientError
    fake_botocore.exceptions.BotoCoreError = FakeBotoCoreError

    with patch.dict(
        "sys.modules",
        {
            "boto3": fake_boto3,
            "botocore": fake_botocore,
            "botocore.exceptions": fake_botocore.exceptions,
        },
    ):
        res = CostAwsExplorerIamCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "SSO" in res[0].message or "sso" in res[0].message.lower()
    assert res[0].suggestion is not None
    assert "aws sso login" in res[0].suggestion
    assert "ws-dev" in res[0].suggestion


# ── project-scope (2026-06-01): 검사 대상 profile 을 실행 중인 프로젝트로 한정 ──

def _deny_session() -> MagicMock:
    """어떤 profile 이든 implicitDeny → WARNING finding 1건 생성용."""
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Arn": "arn:aws:iam::123456789012:user/test"}
    iam = MagicMock()
    iam.simulate_principal_policy.return_value = {
        "EvaluationResults": [{"EvalActionName": REQUIRED_ACTION, "EvalDecision": "implicitDeny"}]
    }
    s = MagicMock()
    s.client.side_effect = lambda name, **_: sts if name == "sts" else iam
    return s


def _run_with_boto3(ctx: CheckContext, session_instance: MagicMock) -> list[CheckResult]:
    fake_boto3 = MagicMock()
    fake_boto3.Session.return_value = session_instance
    fake_botocore = _fake_botocore_modules()
    with patch.dict(
        "sys.modules",
        {
            "boto3": fake_boto3,
            "botocore": fake_botocore,
            "botocore.exceptions": fake_botocore.exceptions,
        },
    ):
        return CostAwsExplorerIamCheck().run(ctx)


def test_scope_none_checks_all_profiles(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scope=None(기본·비-doctor·테스트) → 전 profile 검사 (하위호환). 2 deny → 2 finding."""
    monkeypatch.setattr("anvyc.checks.cost_aws_explorer_iam._boto3_available", lambda: True)
    _write_aws_config(patched_aws_config, ["ws-dev", "ws-prod"])
    res = _run_with_boto3(CheckContext(), _deny_session())
    assert len(res) == 2


def test_scope_filters_to_project_profile(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scope={ws-dev} → 정의된 profile 중 ws-dev 만 검사 (ws-prod skip)."""
    monkeypatch.setattr("anvyc.checks.cost_aws_explorer_iam._boto3_available", lambda: True)
    _write_aws_config(patched_aws_config, ["ws-dev", "ws-prod"])
    res = _run_with_boto3(
        CheckContext(current_project_aws_profiles=frozenset({"ws-dev"})), _deny_session()
    )
    assert len(res) == 1
    assert "ws-dev" in res[0].message
    assert "ws-prod" not in res[0].message


def test_scope_nonmatching_yields_silent(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scope 에 정의된 profile 과 교집합 없음 → silent (profile 순회 전 차단)."""
    monkeypatch.setattr("anvyc.checks.cost_aws_explorer_iam._boto3_available", lambda: True)
    _write_aws_config(patched_aws_config, ["ws-dev"])
    res = CostAwsExplorerIamCheck().run(
        CheckContext(current_project_aws_profiles=frozenset({"unrelated"}))
    )
    assert res == []


def test_scope_empty_silences_including_boto3_warning(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scope=frozenset()(프로젝트 AWS 미사용, 도구 repo) → boto3 미설치 경고까지 silent."""
    monkeypatch.setattr("anvyc.checks.cost_aws_explorer_iam._boto3_available", lambda: False)
    _write_aws_config(patched_aws_config, ["ws-dev"])
    res = CostAwsExplorerIamCheck().run(CheckContext(current_project_aws_profiles=frozenset()))
    assert res == []


def test_scope_active_with_profile_still_warns_boto3_missing(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scope={ws-dev}(프로젝트가 AWS 사용) + boto3 미설치 → boto3 WARNING 유지."""
    monkeypatch.setattr("anvyc.checks.cost_aws_explorer_iam._boto3_available", lambda: False)
    _write_aws_config(patched_aws_config, ["ws-dev"])
    res = CostAwsExplorerIamCheck().run(
        CheckContext(current_project_aws_profiles=frozenset({"ws-dev"}))
    )
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "boto3" in res[0].message


def test_check_registered_in_doctor() -> None:
    """doctor _REGISTRY 에 cost-aws-explorer-iam 키 존재 검증."""
    from anvyc.core.doctor import _REGISTRY  # noqa: PLC0415

    assert "cost-aws-explorer-iam" in _REGISTRY
    assert _REGISTRY["cost-aws-explorer-iam"].name == "cost-aws-explorer-iam"
