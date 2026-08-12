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
    assert str(r.gh_config_dir).endswith("/.config/gh-16bitdo")


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
