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


def test_aws_is_never_emitted_as_a_gate_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AWS 는 차단 범위에서 **제외**다 — 기대값을 방출하면 안 된다 (설계 §6.4).

    §6.4 "차단 범위" 는 `제외  AWS 변경 — aws-prod-account-confirm.sh 가 이미 담당
    (중복 게이트 금지)` 로 AWS 를 명시적으로 제외한다. 그런데 doctor 가
    `expected_aws_profile` 을 방출하면 훅(account-routing-mismatch.sh)의 `aws-profile`
    kind 가 깨어나, manifest `uses.aws` 에 선언된 프로필을 쓴
    `aws s3 ls --profile whatap-dev` 조차 deny 된다 — §9 의 "선언에 없는 도구 자격 →
    warn 후 allow" 와도 어긋나는 신규 차단 경로다. 훅은 `expected_*` **키의 존재**로
    분기하므로(미특정 → allow), 키가 없는 것이 곧 게이트 비활성이다.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = _project(tmp_path, 'export AWS_PROFILE="whatap-prod"\n')
    report = run_project_doctor(proj)
    payload = report.to_payload()

    assert "expected_aws_profile" not in payload
    # 키만 빼고 필드를 남기면 죽은 표면이 되어 다음 사람이 다시 방출한다.
    assert not hasattr(report, "expected_aws_profile"), (
        "expected_aws_profile 필드가 되살아남 — 선언·payload 키·방출을 함께 제거해야 한다"
    )
    # 이름만 바꿔 되살아나는 경우까지 잡는다 — 이 프로젝트는 gh/manifest 선언이
    # 없으므로 방출될 expected_* 가 하나도 없어야 한다.
    assert [k for k in payload if k.startswith("expected_")] == []


def test_aws_removal_does_not_disable_the_gh_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AWS 제거가 남은 게이트 필드까지 죽이지 않았는지 — 과잉 제거 회귀."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = _project(
        tmp_path,
        'export AWS_PROFILE="whatap-prod"\nexport GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n',
    )
    payload = run_project_doctor(proj).to_payload()
    assert [k for k in payload if k.startswith("expected_")] == ["expected_gh_user"]
    assert payload["expected_gh_user"] == "16bitdo"


def test_payload_omits_absent_expected_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """부재 시 키 자체를 넣지 않는다 — 훅의 '미특정 -> allow' 정책을 깨지 않기 위해."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = _project(tmp_path, 'export FOO="bar"\n')
    payload = run_project_doctor(proj).to_payload()
    assert "expected_gh_user" not in payload
    assert set(payload) >= {"path", "results"}


def test_payload_includes_present_expected_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = _project(tmp_path, 'export GH_CONFIG_DIR="$HOME/.config/gh-heisgone"\n')
    payload = run_project_doctor(proj).to_payload()
    assert payload["expected_gh_user"] == "heisgone"
    assert isinstance(payload["results"], list)
    assert payload["path"].endswith("proj")
