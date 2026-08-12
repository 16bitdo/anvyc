"""gh_identity_actual — 선언된 gh 계정과 프로필 토큰의 실체 대조."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.checks.base import Severity
from anvyc.core import project_doctor


def _project(tmp_path: Path, account: str) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".envrc").write_text(
        f'export GH_CONFIG_DIR="$HOME/.config/gh-{account}"\n', encoding="utf-8"
    )
    return proj


def _result(report, name: str):
    return next((r for r in report.results if r.check_name == name), None)


def test_actual_matches_declared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(project_doctor.identity_probe, "gh_login", lambda d: "16bitdo")
    report = project_doctor.run_project_doctor(_project(tmp_path, "16bitdo"))
    res = _result(report, "gh_identity_actual")
    assert res is not None
    assert res.severity is Severity.INFO


def test_actual_differs_is_critical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-08-12 실측 회귀 케이스 — gh-16bitdo 프로필의 토큰이 heisgone 이었다."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(project_doctor.identity_probe, "gh_login", lambda d: "heisgone")
    report = project_doctor.run_project_doctor(_project(tmp_path, "16bitdo"))
    res = _result(report, "gh_identity_actual")
    assert res is not None
    assert res.severity is Severity.CRITICAL
    assert "heisgone" in res.message and "16bitdo" in res.message
    assert report.has_blocking()


def test_probe_failure_is_info_not_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """조회 실패는 모름이지 불일치가 아니다 — 인프라 부재에 fail-closed 를 적용하지 않는다."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(project_doctor.identity_probe, "gh_login", lambda d: None)
    report = project_doctor.run_project_doctor(_project(tmp_path, "16bitdo"))
    res = _result(report, "gh_identity_actual")
    assert res is not None
    assert res.severity is Severity.INFO
    assert not report.has_blocking()


def test_no_gh_account_is_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = tmp_path / "bare"
    proj.mkdir()
    (proj / ".envrc").write_text('export FOO="bar"\n', encoding="utf-8")
    report = project_doctor.run_project_doctor(proj)
    assert _result(report, "gh_identity_actual") is None
