"""project-gh-account-mapping check 단위 테스트.

monkeypatch 로 `DEFAULT_PROJECT_ROOT` 를 격리하여 실제 사용자 환경 의존성 제거.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.project_gh_account import ProjectGhAccountMappingCheck


def _write_origin(project: Path, url: str) -> None:
    """`<project>/.git/config` 에 origin remote 작성."""
    git_dir = project / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "config").write_text(
        textwrap.dedent(f"""\
        [remote "origin"]
            url = {url}
        """)
    )


def _write_envrc_gh(project: Path, account: str) -> Path:
    project.mkdir(parents=True, exist_ok=True)
    e = project / ".envrc"
    e.write_text(f'export GH_CONFIG_DIR="$HOME/.config/gh-{account}"\n')
    return e


@pytest.fixture
def docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Documents"
    root.mkdir()
    monkeypatch.setattr(
        "anvyc.checks.project_gh_account.resolve_project_roots",
        lambda config=None: (str(root),),
    )
    return root


def test_all_routed_yields_single_info(docs: Path) -> None:
    """ssh alias project 의 .envrc GH_CONFIG_DIR 가 모두 일치하면 INFO summary 1건."""
    proj_a = docs / "proj-a"
    _write_origin(proj_a, "git@github.com-16bitdo:16bitdo/proj-a.git")
    _write_envrc_gh(proj_a, "16bitdo")
    proj_b = docs / "proj-b"
    _write_origin(proj_b, "git@github.com-heisgone:whatap/proj-b.git")
    _write_envrc_gh(proj_b, "heisgone")

    res = ProjectGhAccountMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "2개" in res[0].message
    assert "일치" in res[0].message


def test_missing_routing_yields_warning(docs: Path) -> None:
    """ssh alias 쓰는데 .envrc 에 GH_CONFIG_DIR 없으면 WARNING — summary INFO 없음."""
    proj_a = docs / "proj-a"
    _write_origin(proj_a, "git@github.com-16bitdo:16bitdo/proj-a.git")
    _write_envrc_gh(proj_a, "16bitdo")
    proj_b = docs / "proj-b"
    _write_origin(proj_b, "git@github.com-heisgone:whatap/proj-b.git")
    # proj-b 는 .envrc 없음 (라우팅 누락)

    res = ProjectGhAccountMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "heisgone" in res[0].message
    assert "GH_CONFIG_DIR" in res[0].message
    assert res[0].location is not None
    assert res[0].location.name == "proj-b"
    assert res[0].suggestion is not None
    assert "gh-heisgone" in res[0].suggestion


def test_mismatched_account_yields_warning(docs: Path) -> None:
    """gh 계정 ≠ ssh alias 면 WARNING (location = .envrc)."""
    proj = docs / "proj-x"
    _write_origin(proj, "git@github.com-16bitdo:16bitdo/proj-x.git")
    _write_envrc_gh(proj, "heisgone")  # alias 16bitdo 와 불일치

    res = ProjectGhAccountMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "heisgone" in res[0].message
    assert "16bitdo" in res[0].message
    assert "불일치" in res[0].message
    assert res[0].location is not None
    assert res[0].location.name == ".envrc"
    assert res[0].suggestion is not None
    assert "gh-16bitdo" in res[0].suggestion


def test_no_ssh_alias_origin_yields_silent(docs: Path) -> None:
    """origin 이 plain github.com (ssh alias 없음) → 검증 대상 X (silent)."""
    proj = docs / "proj-plain"
    _write_origin(proj, "git@github.com:owner/proj-plain.git")
    _write_envrc_gh(proj, "16bitdo")

    res = ProjectGhAccountMappingCheck().run(CheckContext())
    assert res == []


def test_non_github_origin_yields_silent(docs: Path) -> None:
    """origin 이 GitHub 아님 → 검증 대상 X (silent)."""
    proj = docs / "proj-gitlab"
    _write_origin(proj, "git@gitlab.com:owner/proj-gitlab.git")

    res = ProjectGhAccountMappingCheck().run(CheckContext())
    assert res == []


def test_no_git_dirs_yields_silent(docs: Path) -> None:
    """`.git` 부재 → 결과 0건 (silent)."""
    res = ProjectGhAccountMappingCheck().run(CheckContext())
    assert res == []


def test_https_origin_yields_silent(docs: Path) -> None:
    """HTTPS origin 은 ssh_alias 가 None → 검증 대상 X (silent)."""
    proj = docs / "proj-https"
    _write_origin(proj, "https://github.com/owner/proj-https.git")
    _write_envrc_gh(proj, "16bitdo")

    res = ProjectGhAccountMappingCheck().run(CheckContext())
    assert res == []


def test_envrc_with_quoted_value(docs: Path) -> None:
    """`export GH_CONFIG_DIR="X"` 큰따옴표 + inline comment 형식도 파싱 OK."""
    proj = docs / "proj-q"
    _write_origin(proj, "git@github.com-16bitdo:16bitdo/proj-q.git")
    proj.mkdir(parents=True, exist_ok=True)
    (proj / ".envrc").write_text(
        textwrap.dedent("""\
        # comment
        export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"  # inline comment
        """)
    )

    res = ProjectGhAccountMappingCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO


def test_multi_root_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_project_roots 가 2개 루트를 주면 양쪽 .git 모두 스캔."""
    root_a = tmp_path / "dev"
    root_b = tmp_path / "Documents"
    root_a.mkdir()
    root_b.mkdir()
    proj_a = root_a / "proj-a"
    _write_origin(proj_a, "git@github.com-16bitdo:16bitdo/proj-a.git")
    _write_envrc_gh(proj_a, "16bitdo")
    proj_b = root_b / "proj-b"
    _write_origin(proj_b, "git@github.com-heisgone:whatap/proj-b.git")
    _write_envrc_gh(proj_b, "heisgone")
    monkeypatch.setattr(
        "anvyc.checks.project_gh_account.resolve_project_roots",
        lambda config=None: (str(root_a), str(root_b)),
    )

    res = ProjectGhAccountMappingCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "2개" in res[0].message


def test_envrc_without_gh_config_dir_yields_warning(docs: Path) -> None:
    """`.envrc` 는 있지만 GH_CONFIG_DIR export 가 없으면 라우팅 누락 WARNING."""
    proj = docs / "proj-aws-only"
    _write_origin(proj, "git@github.com-16bitdo:16bitdo/proj-aws-only.git")
    proj.mkdir(parents=True, exist_ok=True)
    (proj / ".envrc").write_text("export AWS_PROFILE=some-profile\n")

    res = ProjectGhAccountMappingCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "GH_CONFIG_DIR" in res[0].message
