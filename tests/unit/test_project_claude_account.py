"""project-claude-account-mapping check 단위 테스트.

monkeypatch 로 `resolve_project_roots` 를 격리하여 실제 사용자 환경 의존성 제거.
`.envrc` 의 CLAUDE_CONFIG_DIR 값은 tmp 절대 경로를 써서 `$HOME` 확장이 실제
홈 디렉터리로 새지 않게 한다.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.project_claude_account import ProjectClaudeAccountMappingCheck


def _write_envrc_claude(project: Path, config_dir: Path) -> Path:
    project.mkdir(parents=True, exist_ok=True)
    e = project / ".envrc"
    e.write_text(f'export CLAUDE_CONFIG_DIR="{config_dir}"\n')
    return e


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    r = tmp_path / "dev"
    r.mkdir()
    monkeypatch.setattr(
        "anvyc.checks.project_claude_account.resolve_project_roots",
        lambda config=None: (str(r),),
    )
    return r


def test_all_dirs_exist_yields_single_info(tmp_path: Path, root: Path) -> None:
    """선언된 CLAUDE_CONFIG_DIR 가 모두 존재하면 INFO summary 1건."""
    cfg_a = tmp_path / ".claude-edward"
    cfg_a.mkdir()
    cfg_b = tmp_path / ".claude-jklee"
    cfg_b.mkdir()
    _write_envrc_claude(root / "proj-a", cfg_a)
    _write_envrc_claude(root / "proj-b", cfg_b)

    res = ProjectClaudeAccountMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "2개" in res[0].message
    assert "모두 존재" in res[0].message


def test_missing_dir_yields_warning(tmp_path: Path, root: Path) -> None:
    """CLAUDE_CONFIG_DIR 디렉터리가 부재하면 WARNING (location = .envrc)."""
    cfg_present = tmp_path / ".claude-edward"
    cfg_present.mkdir()
    cfg_ghost = tmp_path / ".claude-ghost"  # 생성 안 함
    _write_envrc_claude(root / "proj-ok", cfg_present)
    _write_envrc_claude(root / "proj-broken", cfg_ghost)

    res = ProjectClaudeAccountMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert str(cfg_ghost) in res[0].message
    assert res[0].location is not None
    assert res[0].location.name == ".envrc"
    assert res[0].location.parent.name == "proj-broken"
    assert res[0].suggestion is not None


def test_no_claude_config_dir_yields_silent(root: Path) -> None:
    """CLAUDE_CONFIG_DIR 선언한 .envrc 없으면 결과 0건 (silent)."""
    proj = root / "proj-aws-only"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / ".envrc").write_text("export AWS_PROFILE=some-profile\n")

    res = ProjectClaudeAccountMappingCheck().run(CheckContext())
    assert res == []


def test_no_envrc_yields_silent(root: Path) -> None:
    """`.envrc` 자체가 없으면 결과 0건 (silent)."""
    (root / "proj-bare").mkdir(parents=True, exist_ok=True)
    res = ProjectClaudeAccountMappingCheck().run(CheckContext())
    assert res == []


def test_quoted_value_with_inline_comment(tmp_path: Path, root: Path) -> None:
    """큰따옴표 + inline comment 형식 파싱 OK."""
    cfg = tmp_path / ".claude-edward"
    cfg.mkdir()
    proj = root / "proj-q"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / ".envrc").write_text(
        textwrap.dedent(f"""\
        # comment
        export CLAUDE_CONFIG_DIR="{cfg}"  # inline comment
        """)
    )

    res = ProjectClaudeAccountMappingCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO


def test_multi_root_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_project_roots 가 2개 루트를 주면 양쪽 .envrc 모두 스캔."""
    root_a = tmp_path / "dev"
    root_b = tmp_path / "Documents"
    root_a.mkdir()
    root_b.mkdir()
    cfg_a = tmp_path / ".claude-edward"
    cfg_a.mkdir()
    cfg_b = tmp_path / ".claude-jklee"
    cfg_b.mkdir()
    _write_envrc_claude(root_a / "proj-a", cfg_a)
    _write_envrc_claude(root_b / "proj-b", cfg_b)
    monkeypatch.setattr(
        "anvyc.checks.project_claude_account.resolve_project_roots",
        lambda config=None: (str(root_a), str(root_b)),
    )

    res = ProjectClaudeAccountMappingCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "2개" in res[0].message
