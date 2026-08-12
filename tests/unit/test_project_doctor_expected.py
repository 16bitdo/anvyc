"""project doctor 의 expected_* 방출 — 훅이 소비하는 C2 계약."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core.project_doctor import run_project_doctor


def _project(tmp_path: Path, envrc: str) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".envrc").write_text(envrc, encoding="utf-8")
    return proj


def test_expected_gh_user_from_envrc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = _project(tmp_path, 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n')
    report = run_project_doctor(proj)
    assert report.expected_gh_user == "16bitdo"


def test_expected_aws_profile_from_envrc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = _project(tmp_path, 'export AWS_PROFILE="whatap-dev"\n')
    report = run_project_doctor(proj)
    assert report.expected_aws_profile == "whatap-dev"


def test_payload_omits_absent_expected_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """부재 시 키 자체를 넣지 않는다 — 훅의 '미특정 -> allow' 정책을 깨지 않기 위해."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = _project(tmp_path, 'export FOO="bar"\n')
    payload = run_project_doctor(proj).to_payload()
    assert "expected_gh_user" not in payload
    assert "expected_aws_profile" not in payload
    assert set(payload) >= {"path", "results"}


def test_payload_includes_present_expected_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = _project(tmp_path, 'export GH_CONFIG_DIR="$HOME/.config/gh-heisgone"\n')
    payload = run_project_doctor(proj).to_payload()
    assert payload["expected_gh_user"] == "heisgone"
    assert isinstance(payload["results"], list)
    assert payload["path"].endswith("proj")
