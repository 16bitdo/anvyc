"""account manifest — L1 프로젝트맵 + 머신 바인딩 조인."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core import account_manifest

_PROJECTS = """
version: 1
projects:
  - id: analysis
    repo: 16bitdo/analysis
    ownership: personal-16bitdo
    uses:
      aws: [whatap-dev]
  - id: devops-shell-script
    repo: whatap/devops-shell-script
    ownership: work-heisgone
"""

_BINDINGS = """
version: 1
machine: test-machine
accounts:
  personal-16bitdo:
    github_login: 16bitdo
    commit_email: 16bitdo@gmail.com
    ssh_alias: github.com-16bitdo
    gh_config_dir: ~/.config/gh-16bitdo
    claude_config_dir: ~/.claude
  work-heisgone:
    github_login: heisgone
    commit_email: jklee@whatap.io
    ssh_alias: github.com-heisgone
    gh_config_dir: ~/.config/gh-heisgone
"""


@pytest.fixture()
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    rbr = tmp_path / "rbr" / "metadata"
    rbr.mkdir(parents=True)
    (rbr / "account-routing.yaml").write_text(_PROJECTS, encoding="utf-8")
    binds = tmp_path / "anvyc" / "accounts"
    binds.mkdir(parents=True)
    (binds / "bindings.test-machine.yaml").write_text(_BINDINGS, encoding="utf-8")
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(rbr / "account-routing.yaml"))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(binds))
    monkeypatch.setattr(account_manifest, "machine_name", lambda: "test-machine")
    return tmp_path


def test_resolve_joins_project_and_binding(wired: Path) -> None:
    r = account_manifest.resolve("16bitdo/analysis")
    assert r is not None
    assert r.ownership_id == "personal-16bitdo"
    assert r.github_login == "16bitdo"
    assert r.commit_email == "16bitdo@gmail.com"
    assert r.ssh_alias == "github.com-16bitdo"
    # `.endswith()` 는 미확장 문자열("~/.config/gh-16bitdo" 그대로)도 같은 접미사로
    # 끝나므로 `_expand()` 가 실제로 `~` 를 홈 디렉터리로 바꿨는지 못 잡는다(완전 일치로
    # 검증 — `_expand` 의 `os.path.expanduser` 호출을 제거해도 이전엔 5/5 PASS 였음).
    assert r.gh_config_dir == Path.home() / ".config" / "gh-16bitdo"
    assert r.claude_config_dir == Path.home() / ".claude"


def test_resolve_unknown_repo_returns_none(wired: Path) -> None:
    assert account_manifest.resolve("16bitdo/nope") is None


def test_resolve_without_binding_returns_partial(wired: Path, tmp_path: Path) -> None:
    """프로젝트는 선언됐으나 이 머신 바인딩이 없으면 ownership_id 만 채운다."""
    binds = tmp_path / "anvyc" / "accounts" / "bindings.test-machine.yaml"
    binds.write_text("version: 1\nmachine: test-machine\naccounts: {}\n", encoding="utf-8")
    r = account_manifest.resolve("16bitdo/analysis")
    assert r is not None
    assert r.ownership_id == "personal-16bitdo"
    assert r.github_login is None
    assert r.commit_email is None


def test_missing_manifest_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(tmp_path / "nope"))
    assert account_manifest.load_projects() == {}
    assert account_manifest.resolve("16bitdo/analysis") is None


def test_declared_uses_are_exposed(wired: Path) -> None:
    projects = account_manifest.load_projects()
    assert projects["16bitdo/analysis"].uses == {"aws": ["whatap-dev"]}
    assert projects["whatap/devops-shell-script"].uses == {}


def test_scalar_projects_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`projects` 가 매핑도 리스트도 아닌 truthy 스칼라(정수)면 예외 대신 빈 dict.

    `data.get("projects") or []` 관용구는 falsy 값에만 폴백한다 — truthy 스칼라(예: 42)는
    폴백을 우회해 `for p in 42` 가 TypeError 로 죽는다(회귀 재현: mutation 으로 확인함).
    manifest 파손 시 예외를 던지지 않는다는 계약을 지켜야 한다.
    """
    manifest = tmp_path / "account-routing.yaml"
    manifest.write_text("version: 1\nprojects: 42\n", encoding="utf-8")
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(manifest))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(tmp_path / "nope"))
    assert account_manifest.load_projects() == {}
    assert account_manifest.resolve("16bitdo/analysis") is None


def test_malformed_manifest_yaml_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L1 manifest 가 YAML 문법 오류면 예외 대신 빈 dict — '파손' 은 파싱 실패도 포함한다."""
    manifest = tmp_path / "account-routing.yaml"
    manifest.write_text("version: 1\nprojects: [unclosed\n", encoding="utf-8")
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(manifest))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(tmp_path / "nope"))
    assert account_manifest.load_projects() == {}
    assert account_manifest.resolve("16bitdo/analysis") is None


def test_malformed_bindings_yaml_returns_partial(wired: Path, tmp_path: Path) -> None:
    """L2 바인딩이 YAML 문법 오류면 예외 대신, 미바인딩과 동일하게 ownership_id 만 채운다."""
    binds = tmp_path / "anvyc" / "accounts" / "bindings.test-machine.yaml"
    binds.write_text("version: 1\naccounts: [unclosed\n", encoding="utf-8")
    assert account_manifest.load_bindings() == {}
    r = account_manifest.resolve("16bitdo/analysis")
    assert r is not None
    assert r.ownership_id == "personal-16bitdo"
    assert r.github_login is None


def test_resolve_expands_home_env_var_and_tilde_exactly(
    wired: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`~`(홈 디렉터리 확장)와 `$HOME`(환경변수 확장)은 서로 다른 메커니즘 — 둘 다 검증한다.

    기존 픽스처에는 `$HOME`/`${HOME}` 형태가 전혀 없어 `os.path.expandvars` 경로가
    커버리지 0 이었다(Task 4 에서 `Path.expanduser()` 가 `$HOME` 을 확장 못 해 기능이
    죽은 채 테스트가 통과했던 전례와 동일 계열 위험). `HOME` 을 알려진 임시 경로로
    고정해 두 확장 결과 모두 완전 일치로 검증한다.
    """
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    binds = tmp_path / "anvyc" / "accounts" / "bindings.test-machine.yaml"
    binds.write_text(
        "version: 1\n"
        "machine: test-machine\n"
        "accounts:\n"
        "  personal-16bitdo:\n"
        "    github_login: 16bitdo\n"
        "    gh_config_dir: ~/.config/gh-16bitdo\n"
        "    claude_config_dir: $HOME/.claude\n",
        encoding="utf-8",
    )

    r = account_manifest.resolve("16bitdo/analysis")
    assert r is not None
    assert r.gh_config_dir == fake_home / ".config" / "gh-16bitdo"
    assert r.claude_config_dir == fake_home / ".claude"
