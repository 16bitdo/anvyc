"""project show 가 ownership 선언을 gh_account 라벨과 함께 보이는지 검증.

`gh_account` 는 `.envrc` GH_CONFIG_DIR 에서 유도한 라벨이라 실체(정책상 소유자)와
다를 수 있다 — account-routing manifest(L1)가 선언한 ownership 을 병기해 어느 쪽이
정책 SoT 인지 드러내는 것이 이 기능의 목적이다. 미선언 저장소는 조용히 생략되지
않고 "(미선언)" 으로 명시돼야 한다(선언 누락을 발견할 수 있어야 하므로).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anvyc.cli import app
from anvyc.core import account_manifest

_PROJECTS = """
version: 1
projects:
  - id: analysis
    repo: 16bitdo/analysis
    ownership: personal-16bitdo
"""
_BINDINGS = """
version: 1
machine: test-machine
accounts:
  personal-16bitdo:
    github_login: 16bitdo
    commit_email: 16bitdo@gmail.com
    gh_config_dir: ~/.config/gh-16bitdo
"""
# "부분 결과" 시나리오용 — manifest 는 personal-16bitdo 를 선언하지만 이 머신
# bindings 에는 그 계정이 없다(다른 계정만 있음). account_manifest.resolve() 의
# 문서화된 계약: ownership_id 만 채운 ResolvedAccount 를 반환(다른 필드는 None).
_BINDINGS_MISSING_ACCOUNT = """
version: 1
machine: test-machine
accounts:
  work-heisgone:
    github_login: heisgone
    commit_email: jklee@whatap.io
    gh_config_dir: ~/.config/gh-heisgone
"""


def _setup_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, bindings_yaml: str = _BINDINGS
) -> None:
    """account-routing manifest + 이 머신 bindings 를 tmp_path 에 만들고 env 로 주입.

    bindings_yaml 을 바꿔 넣으면 "선언은 있으나 이 머신 바인딩 없음"(부분 결과)
    같은 시나리오도 동일 헬퍼로 구성할 수 있다.
    """
    m = tmp_path / "account-routing.yaml"
    m.write_text(_PROJECTS, encoding="utf-8")
    b = tmp_path / "binds"
    b.mkdir()
    (b / "bindings.test-machine.yaml").write_text(bindings_yaml, encoding="utf-8")
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(m))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(b))
    monkeypatch.setattr(account_manifest, "machine_name", lambda: "test-machine")


def _repo_with_origin(tmp_path: Path, name: str, url: str) -> Path:
    proj = tmp_path / name
    (proj / ".git").mkdir(parents=True)
    (proj / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8")
    return proj


def test_show_reports_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """manifest 에 선언된 저장소 — ownership_id 와 commit_email 이 출력에 보여야 한다."""
    _setup_manifest(tmp_path, monkeypatch)
    proj = _repo_with_origin(tmp_path, "analysis", "git@github.com:16bitdo/analysis.git")

    result = CliRunner().invoke(app, ["project", "show", "--path", str(proj)])
    assert result.exit_code == 0
    assert "personal-16bitdo" in result.stdout
    assert "ownership" in result.stdout
    assert "16bitdo@gmail.com" in result.stdout


def test_show_reports_partial_resolution_without_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """manifest 선언은 있으나 이 머신 bindings 에 해당 계정이 없는 "부분 결과" 케이스.

    account_manifest.resolve() 는 이때 ownership_id 만 채운 ResolvedAccount 를
    돌려준다(commit_email 등 나머지 필드는 전부 None) — "미선언"과는 구분되는
    상태다. 출력이 깨지지 않고 ownership_id 는 보이되 commit_email 줄은 조용히
    생략돼야 한다(리뷰 I1 — mutation 으로 `if _resolved.commit_email:` guard 를
    제거해도 통과하던 공백을 메운다).
    """
    _setup_manifest(tmp_path, monkeypatch, bindings_yaml=_BINDINGS_MISSING_ACCOUNT)
    proj = _repo_with_origin(tmp_path, "analysis", "git@github.com:16bitdo/analysis.git")

    result = CliRunner().invoke(app, ["project", "show", "--path", str(proj)])
    assert result.exit_code == 0
    assert "ownership personal-16bitdo" in result.stdout
    assert "commit_email" not in result.stdout


def test_show_reports_undeclared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """manifest 에 없는 저장소 — 조용히 생략되지 않고 "(미선언)" 으로 명시돼야 한다."""
    _setup_manifest(tmp_path, monkeypatch)
    proj = _repo_with_origin(tmp_path, "other", "git@github.com:acme/other.git")

    result = CliRunner().invoke(app, ["project", "show", "--path", str(proj)])
    assert result.exit_code == 0
    assert "미선언" in result.stdout
    assert "acme/other" in result.stdout
    # 다른 프로젝트(analysis)의 ownership_id 가 잘못 새어 나오지 않는지도 함께 확인.
    assert "personal-16bitdo" not in result.stdout


def test_show_no_remote_omits_ownership_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """origin remote 자체가 없으면(비 git 디렉터리) ownership 판단 대상이 아니다."""
    _setup_manifest(tmp_path, monkeypatch)
    proj = tmp_path / "no_git"
    proj.mkdir()

    result = CliRunner().invoke(app, ["project", "show", "--path", str(proj)])
    assert result.exit_code == 0
    assert "ownership" not in result.stdout


def test_show_json_output_unaffected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json 은 project_info.to_dict 그대로 — ownership 은 human 렌더에만 추가된다.

    manifest 파생 필드를 기계가독으로 원하면 `project doctor --json` 의
    expected_gh_user/expected_commit_email(run_project_doctor 가 채움) 이 이미 그
    역할을 한다. project show --json 은 기존 계약(순수 환경 수집 결과)을 유지해
    소비자를 깨지 않는다.
    """
    _setup_manifest(tmp_path, monkeypatch)
    proj = _repo_with_origin(tmp_path, "analysis", "git@github.com:16bitdo/analysis.git")

    result = CliRunner().invoke(app, ["project", "show", "--path", str(proj), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "ownership" not in payload
    assert set(payload.keys()) == {
        "path",
        "aws_profile",
        "gh_account",
        "claude_account",
        "github",
        "pulumi",
        "dev_env",
        "tool_versions",
    }
