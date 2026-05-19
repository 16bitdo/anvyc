"""dev_env adapter 단위 테스트 — tmp_path 로 fake project tree 구성."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.adapters.dev_env import DEFAULT_PATTERNS, DevEnvAdapter


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# fixture\n")
    return p


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    """tmp_path/projects/<group>/<proj>/{.envrc, .tool-versions, ...} 트리."""
    root = tmp_path / "projects"
    _touch(root / "alpha" / ".envrc")
    _touch(root / "alpha" / ".tool-versions")
    _touch(root / "beta" / ".python-version")
    _touch(root / "beta" / ".nvmrc")
    # 깊이 4 — depth 제한으로 수집 안 됨
    _touch(root / "gamma" / "sub1" / "sub2" / ".envrc")
    # 제외 대상
    _touch(root / "delta" / "node_modules" / ".envrc")
    _touch(root / "epsilon" / ".venv" / "lib" / ".envrc")
    # not in patterns
    _touch(root / "zeta" / "README.md")
    return root


def test_detect_true_when_root_exists(projects: Path) -> None:
    a = DevEnvAdapter(project_roots=(str(projects),))
    assert a.detect() is True


def test_detect_false_when_root_absent(tmp_path: Path) -> None:
    a = DevEnvAdapter(project_roots=(str(tmp_path / "nonexistent"),))
    assert a.detect() is False


def test_collect_finds_all_default_patterns(projects: Path) -> None:
    a = DevEnvAdapter(project_roots=(str(projects),), max_depth=3)
    mfs = a.collect()
    names = {mf.source_path.name for mf in mfs}
    # 4 default patterns 모두 발견
    for p in DEFAULT_PATTERNS:
        assert p in names, f"missing pattern: {p}"


def test_collect_respects_depth_limit(projects: Path) -> None:
    """gamma/sub1/sub2/.envrc 는 depth 4 라 제외."""
    a = DevEnvAdapter(project_roots=(str(projects),), max_depth=3)
    mfs = a.collect()
    deep = [mf for mf in mfs if "sub2" in str(mf.source_path)]
    assert deep == []


def test_collect_respects_exclude_globs(projects: Path) -> None:
    """node_modules / .venv 안의 매칭 파일은 제외."""
    a = DevEnvAdapter(project_roots=(str(projects),), max_depth=5)
    mfs = a.collect()
    paths = [str(mf.source_path) for mf in mfs]
    assert not any("node_modules" in p for p in paths)
    assert not any(".venv" in p for p in paths)


def test_collect_custom_patterns_only(projects: Path) -> None:
    """`patterns=(.envrc,)` 만 지정 → .envrc 만 수집."""
    a = DevEnvAdapter(project_roots=(str(projects),), patterns=(".envrc",))
    mfs = a.collect()
    names = {mf.source_path.name for mf in mfs}
    assert names == {".envrc"}


def test_exclude_returns_configured_globs(tmp_path: Path) -> None:
    a = DevEnvAdapter(
        project_roots=(str(tmp_path),),
        excludes=("**/build/**", "**/dist/**"),
    )
    excl = a.exclude()
    assert "**/build/**" in excl
    assert "**/dist/**" in excl
