"""Unit tests for anvyc.core.creds rotate (CP-5 3/3)."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from anvyc.core.creds import (
    KIND_AWS_SSO,
    KIND_CLAUDE_OAUTH,
    KIND_GITHUB,
    ROTATE_KINDS,
    RotateError,
    plan_rotate,
    rotate_credential,
)


def test_rotate_kinds_constant() -> None:
    """ROTATE_KINDS 가 3 종 모두 포함."""
    assert set(ROTATE_KINDS) == {KIND_AWS_SSO, KIND_GITHUB, KIND_CLAUDE_OAUTH}


def test_plan_aws_sso() -> None:
    plan = plan_rotate(KIND_AWS_SSO)
    assert plan.kind == KIND_AWS_SSO
    assert plan.command == ["aws", "sso", "login"]
    assert "AWS SSO" in plan.description
    assert len(plan.warnings) >= 1


def test_plan_github() -> None:
    plan = plan_rotate(KIND_GITHUB)
    assert plan.kind == KIND_GITHUB
    assert plan.command == ["gh", "auth", "refresh"]
    assert "OAuth" in plan.description or "refresh" in plan.description
    # PAT 안내 warning 1개 이상
    assert any("PAT" in w or "gh auth login" in w for w in plan.warnings)


def test_plan_claude_oauth_no_command() -> None:
    """claude_oauth 는 command 가 빈 list — 사용자 수동 조치 안내만."""
    plan = plan_rotate(KIND_CLAUDE_OAUTH)
    assert plan.kind == KIND_CLAUDE_OAUTH
    assert plan.command == []
    # warnings 에 수동 절차 1단계 이상
    assert len(plan.warnings) >= 2


def test_plan_unsupported_kind_raises() -> None:
    with pytest.raises(RotateError, match="unsupported kind"):
        plan_rotate("foo")


def test_rotate_claude_oauth_no_op() -> None:
    """command 가 빈 list 면 executed=False — subprocess 호출 없음."""
    with patch("anvyc.core.creds.subprocess.run") as mock_run:
        result = rotate_credential(KIND_CLAUDE_OAUTH)
    mock_run.assert_not_called()
    assert result.executed is False
    assert result.return_code is None
    assert "수동" in result.note


def test_rotate_aws_sso_executes_subprocess() -> None:
    """aws_sso 는 subprocess 호출 + 결과 반환."""
    fake_proc = MagicMock(returncode=0, stdout="logged in\n", stderr="")
    with patch("anvyc.core.creds.subprocess.run", return_value=fake_proc) as mock_run:
        result = rotate_credential(KIND_AWS_SSO, timeout_seconds=10)
    mock_run.assert_called_once()
    # 호출 인자 검증
    call_args = mock_run.call_args
    assert call_args.args[0] == ["aws", "sso", "login"]
    assert call_args.kwargs.get("timeout") == 10
    assert call_args.kwargs.get("capture_output") is True
    assert result.executed is True
    assert result.return_code == 0
    assert "logged in" in result.stdout_tail


def test_rotate_github_non_zero_exit_returned() -> None:
    """exit non-zero 도 RotateError 없이 결과로 반환 (caller 가 판단)."""
    fake_proc = MagicMock(returncode=2, stdout="", stderr="auth failed\n")
    with patch("anvyc.core.creds.subprocess.run", return_value=fake_proc):
        result = rotate_credential(KIND_GITHUB)
    assert result.executed is True
    assert result.return_code == 2
    assert "auth failed" in result.stderr_tail


def test_rotate_command_not_found_raises() -> None:
    """외부 명령 부재 → RotateError."""
    with patch(
        "anvyc.core.creds.subprocess.run",
        side_effect=FileNotFoundError(2, "No such file or directory: aws"),
    ), pytest.raises(RotateError, match="외부 명령 부재"):
        rotate_credential(KIND_AWS_SSO)


def test_rotate_timeout_raises() -> None:
    """subprocess.TimeoutExpired → RotateError (안내 message)."""
    with patch(
        "anvyc.core.creds.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="aws sso login", timeout=10),
    ), pytest.raises(RotateError, match="timeout"):
        rotate_credential(KIND_AWS_SSO, timeout_seconds=10)


def test_rotate_invalid_kind_raises() -> None:
    with pytest.raises(RotateError, match="unsupported kind"):
        rotate_credential("invalid")


def test_rotate_stdout_truncated_to_2kib() -> None:
    """stdout 이 길어도 tail 2 KiB 만 캡처 — token 본문 노출 회피."""
    long_output = "x" * 10000
    fake_proc = MagicMock(returncode=0, stdout=long_output, stderr="")
    with patch("anvyc.core.creds.subprocess.run", return_value=fake_proc):
        result = rotate_credential(KIND_GITHUB)
    assert len(result.stdout_tail) == 2048
    # 마지막 부분이 보존되는지
    assert result.stdout_tail == long_output[-2048:]
