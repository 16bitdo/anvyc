"""aws-account-status 전역 doctor 체크 — cwd 프로젝트 scope."""
from pathlib import Path

import pytest

from anvyc.checks.aws_account_status import AwsAccountStatusCheck
from anvyc.checks.base import CheckContext, Severity


def _home(tmp_path: Path, config: str) -> Path:
    aws = tmp_path / ".aws"
    aws.mkdir(parents=True)
    (aws / "config").write_text(config, encoding="utf-8")
    return tmp_path


def test_silent_when_scope_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path, "[profile dev]\nregion = x\n")))
    # scope=None(기본) / frozenset() 모두 silent.
    assert AwsAccountStatusCheck().run(CheckContext()) == []
    assert AwsAccountStatusCheck().run(CheckContext(current_project_aws_profiles=frozenset())) == []


def test_reports_undefined_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path, "[profile other]\nregion = x\n")))
    ctx = CheckContext(current_project_aws_profiles=frozenset({"ghost"}))
    res = AwsAccountStatusCheck().run(ctx)
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert res[0].check_name == "aws-account-status"
    assert "미정의" in res[0].message


def test_reports_static_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = _home(tmp_path, "[profile legacy]\nregion = us-east-1\n")
    (home / ".aws" / "credentials").write_text("[legacy]\naws_access_key_id = AKIA_X\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    ctx = CheckContext(current_project_aws_profiles=frozenset({"legacy"}))
    res = AwsAccountStatusCheck().run(ctx)
    assert len(res) == 1 and res[0].severity is Severity.INFO
