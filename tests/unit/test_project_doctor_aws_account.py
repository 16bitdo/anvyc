"""project doctor 의 aws_account_status 체크."""
from pathlib import Path

import pytest

from anvyc.core.project_doctor import run_project_doctor


def _home_with_profile(tmp_path: Path) -> Path:
    aws = tmp_path / "home" / ".aws"
    aws.mkdir(parents=True)
    (aws / "config").write_text(
        "[profile ws-dev]\nregion = ap-northeast-2\n", encoding="utf-8"
    )
    (aws / "credentials").write_text(
        "[ws-dev]\naws_access_key_id = AKIA_X\n", encoding="utf-8"
    )
    return tmp_path / "home"


def test_project_doctor_reports_aws_account_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(_home_with_profile(tmp_path)))
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".envrc").write_text('export AWS_PROFILE="ws-dev"\n', encoding="utf-8")

    report = run_project_doctor(proj)
    names = {r.check_name for r in report.results}
    assert "aws_account_status" in names
    acc = next(r for r in report.results if r.check_name == "aws_account_status")
    assert "ws-dev" in acc.message


def test_project_doctor_no_aws_profile_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(_home_with_profile(tmp_path)))
    proj = tmp_path / "proj2"
    proj.mkdir()
    (proj / ".envrc").write_text('export FOO="bar"\n', encoding="utf-8")

    report = run_project_doctor(proj)
    assert "aws_account_status" not in {r.check_name for r in report.results}


def test_project_doctor_undefined_profile_defers_to_aws_profile_defined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # .envrc 가 ~/.aws/config 에 없는 profile 을 가리킴 → aws_account_status 는 침묵(state.defined=False),
    # 미정의 WARNING 은 기존 aws_profile_defined 가 발행 (중복 WARNING 방지 설계 검증).
    monkeypatch.setenv("HOME", str(_home_with_profile(tmp_path)))
    proj = tmp_path / "proj_ghost"
    proj.mkdir()
    (proj / ".envrc").write_text('export AWS_PROFILE="ghost"\n', encoding="utf-8")

    report = run_project_doctor(proj)
    names = [r.check_name for r in report.results]
    assert "aws_account_status" not in names
    assert "aws_profile_defined" in names  # 미정의는 이 체크가 보고
