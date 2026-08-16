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
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(root),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: ())
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    return root


def test_all_routed_yields_single_info(docs: Path) -> None:
    """ssh alias project 의 .envrc GH_CONFIG_DIR 가 모두 일치하면 INFO summary 1건."""
    proj_a = docs / "proj-a"
    _write_origin(proj_a, "git@github.com-16bitdo:16bitdo/proj-a.git")
    _write_envrc_gh(proj_a, "16bitdo")
    proj_b = docs / "proj-b"
    _write_origin(proj_b, "git@github.com-secondary:acme/proj-b.git")
    _write_envrc_gh(proj_b, "secondary")

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
    _write_origin(proj_b, "git@github.com-secondary:acme/proj-b.git")
    # proj-b 는 .envrc 없음 (라우팅 누락)

    res = ProjectGhAccountMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "secondary" in res[0].message
    assert "GH_CONFIG_DIR" in res[0].message
    assert res[0].location is not None
    assert res[0].location.name == "proj-b"
    assert res[0].suggestion is not None
    assert "gh-secondary" in res[0].suggestion


def test_mismatched_account_yields_warning(docs: Path) -> None:
    """gh 계정 ≠ ssh alias 면 WARNING (location = .envrc)."""
    proj = docs / "proj-x"
    _write_origin(proj, "git@github.com-16bitdo:16bitdo/proj-x.git")
    _write_envrc_gh(proj, "secondary")  # alias 16bitdo 와 불일치

    res = ProjectGhAccountMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "secondary" in res[0].message
    assert "16bitdo" in res[0].message
    assert "불일치" in res[0].message
    assert res[0].location is not None
    assert res[0].location.name == ".envrc"
    assert res[0].suggestion is not None
    assert "gh-16bitdo" in res[0].suggestion


def test_no_ssh_alias_origin_yields_silent(docs: Path) -> None:
    """plain github.com origin + owner 가 gh_owner_accounts 에 없음 → silent (무오탐)."""
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
    """HTTPS origin + owner 가 gh_owner_accounts 에 없음 → silent (무오탐)."""
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
    _write_origin(proj_b, "git@github.com-secondary:acme/proj-b.git")
    _write_envrc_gh(proj_b, "secondary")
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(root_a), str(root_b)))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: ())
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())

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


# ── owner↔alias 라우팅 검증 (gh_owner_accounts, static+dynamic) ──
def test_owner_alias_match_no_owner_warn(docs: Path) -> None:
    """owner 매핑 일치(16bitdo→16bitdo) → owner-routing finding 없음."""
    proj = docs / "p"
    _write_origin(proj, "git@github.com-16bitdo:16bitdo/p.git")
    _write_envrc_gh(proj, "16bitdo")
    res = ProjectGhAccountMappingCheck().run(
        CheckContext(gh_owner_accounts={"16bitdo": "16bitdo"})
    )
    assert not any("misroute" in r.message for r in res)
    assert all(r.severity is Severity.INFO for r in res)  # alias↔envrc summary 만


def test_owner_alias_mismatch_no_write_warns(
    docs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """whatap repo 가 16bitdo alias 로 박혔고 그 계정 write 없음 → WARNING(misroute)."""
    proj = docs / "p"
    _write_origin(proj, "git@github.com-16bitdo:whatap/p.git")
    _write_envrc_gh(proj, "16bitdo")  # alias↔envrc 는 self-consistent(둘 다 16bitdo)
    monkeypatch.setattr(
        "anvyc.checks.project_gh_account._repo_write_access", lambda o, r, a: False
    )
    res = ProjectGhAccountMappingCheck().run(
        CheckContext(gh_owner_accounts={"whatap": "heisgone"})
    )
    assert any(r.severity is Severity.WARNING and "misroute" in r.message for r in res)


def test_owner_alias_mismatch_with_write_info(
    docs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """불일치이나 routed 계정 write 가능 → INFO(이탈/확인 권고), WARNING 아님."""
    proj = docs / "p"
    _write_origin(proj, "git@github.com-16bitdo:whatap/p.git")
    _write_envrc_gh(proj, "16bitdo")
    monkeypatch.setattr(
        "anvyc.checks.project_gh_account._repo_write_access", lambda o, r, a: True
    )
    res = ProjectGhAccountMappingCheck().run(
        CheckContext(gh_owner_accounts={"whatap": "heisgone"})
    )
    assert any(r.severity is Severity.INFO and "불일치" in r.message for r in res)
    assert not any(r.severity is Severity.WARNING and "misroute" in r.message for r in res)


def test_owner_not_in_mapping_skips_dynamic(
    docs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """매핑에 없는 owner(pyroscopy) → owner-routing skip, dynamic 미호출."""
    proj = docs / "p"
    _write_origin(proj, "git@github.com-16bitdo:pyroscopy/p.git")
    _write_envrc_gh(proj, "16bitdo")
    calls = {"n": 0}

    def _spy(o: str, r: str, a: str) -> bool | None:
        calls["n"] += 1
        return False

    monkeypatch.setattr("anvyc.checks.project_gh_account._repo_write_access", _spy)
    res = ProjectGhAccountMappingCheck().run(
        CheckContext(gh_owner_accounts={"whatap": "heisgone"})
    )
    assert calls["n"] == 0
    assert not any("misroute" in r.message for r in res)


def test_owner_routing_disabled_when_mapping_empty(
    docs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gh_owner_accounts 미설정 → owner-routing 완전 skip(기존 동작 불변), dynamic 미호출."""
    proj = docs / "p"
    _write_origin(proj, "git@github.com-16bitdo:whatap/p.git")
    _write_envrc_gh(proj, "16bitdo")
    calls = {"n": 0}

    def _spy(o: str, r: str, a: str) -> bool | None:
        calls["n"] += 1
        return False

    monkeypatch.setattr("anvyc.checks.project_gh_account._repo_write_access", _spy)
    res = ProjectGhAccountMappingCheck().run(CheckContext())  # 빈 매핑
    assert calls["n"] == 0
    assert not any("misroute" in r.message for r in res)


# ── 별칭 미사용 origin 검출 (issue #198) ──
def test_unaliased_origin_warns_when_owner_mapped(docs: Path) -> None:
    """plain github.com origin 이고 owner 가 매핑에 등록됐으면 WARNING."""
    proj = docs / "proj-plain"
    _write_origin(proj, "git@github.com:16bitdo/proj-plain.git")

    res = ProjectGhAccountMappingCheck().run(
        CheckContext(gh_owner_accounts={"16bitdo": "16bitdo"})
    )

    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "별칭 없는" in res[0].message
    assert "16bitdo/proj-plain" in res[0].message
    assert res[0].location is not None
    assert res[0].location.name == "proj-plain"
    assert res[0].suggestion is not None
    assert "git@github.com-16bitdo:16bitdo/proj-plain.git" in res[0].suggestion


def test_unaliased_origin_silent_when_owner_unmapped(docs: Path) -> None:
    """매핑에 없는 owner 의 별칭 미사용 origin 은 종전대로 silent."""
    proj = docs / "proj-plain"
    _write_origin(proj, "git@github.com:acme/proj-plain.git")

    res = ProjectGhAccountMappingCheck().run(
        CheckContext(gh_owner_accounts={"16bitdo": "16bitdo"})
    )
    assert res == []


def test_unaliased_https_origin_warns_when_owner_mapped(docs: Path) -> None:
    """https origin 도 별칭 라우팅이 아니므로 owner 등록 시 WARNING."""
    proj = docs / "proj-https"
    _write_origin(proj, "https://github.com/16bitdo/proj-https.git")

    res = ProjectGhAccountMappingCheck().run(
        CheckContext(gh_owner_accounts={"16bitdo": "16bitdo"})
    )

    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "https" in res[0].message


def test_unaliased_warning_coexists_with_alias_findings(docs: Path) -> None:
    """별칭 project 의 라우팅 누락 WARNING 과 별칭 미사용 WARNING 이 함께 보고된다."""
    aliased = docs / "proj-a"
    _write_origin(aliased, "git@github.com-16bitdo:16bitdo/proj-a.git")  # .envrc 없음
    plain = docs / "proj-b"
    _write_origin(plain, "git@github.com:16bitdo/proj-b.git")

    res = ProjectGhAccountMappingCheck().run(
        CheckContext(gh_owner_accounts={"16bitdo": "16bitdo"})
    )

    assert len(res) == 2
    assert all(r.severity is Severity.WARNING for r in res)
    assert any("GH_CONFIG_DIR" in r.message for r in res)
    assert any("별칭 없는" in r.message for r in res)


# ── 매핑 미설정 시 skip 사실 표기 (issue #198) ──
def test_summary_notes_skip_when_mapping_empty(docs: Path) -> None:
    """gh_owner_accounts 미설정이면 summary INFO 에 skip 사실을 표기."""
    proj = docs / "proj-a"
    _write_origin(proj, "git@github.com-16bitdo:16bitdo/proj-a.git")
    _write_envrc_gh(proj, "16bitdo")

    res = ProjectGhAccountMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "skip" in res[0].message
    assert "gh_owner_accounts" in res[0].message


def test_summary_has_no_skip_note_when_mapping_set(docs: Path) -> None:
    """매핑이 설정돼 있으면 skip 문구가 붙지 않는다."""
    proj = docs / "proj-a"
    _write_origin(proj, "git@github.com-16bitdo:16bitdo/proj-a.git")
    _write_envrc_gh(proj, "16bitdo")

    res = ProjectGhAccountMappingCheck().run(
        CheckContext(gh_owner_accounts={"16bitdo": "16bitdo"})
    )

    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "skip" not in res[0].message


def test_gh_honors_individual_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """개별 project (projects 설정) 가 스캔에 포함된다."""
    empty = tmp_path / "empty"
    empty.mkdir()
    indiv = tmp_path / "proj"
    (indiv / ".git").mkdir(parents=True)
    (indiv / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com-16bitdo:16bitdo/x.git\n'
    )
    # .envrc 에 GH_CONFIG_DIR 없음 → alias 라우팅 누락 경고 기대
    # (P3) core 3종 패치 — refactor 후 iter_project_dirs 가 이를 통해 격리됨
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(empty),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    results = ProjectGhAccountMappingCheck().run(CheckContext())
    # refactor 전: empty root 스캔 → indiv 미포함 → results 비어 assert FAIL
    # refactor 후: resolve_projects → indiv 포함 → "16bitdo" 경고 → assert PASS
    assert any("proj" in r.message or "16bitdo" in r.message for r in results)
