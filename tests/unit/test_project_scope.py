"""core.project_scope — walk 원시 단위 테스트."""
from __future__ import annotations

from pathlib import Path

from anvyc.core.config import AnvycConfig
from anvyc.core.project_scope import _has_any_marker, _walk_markers, iter_project_dirs


def test_has_any_marker_file_or_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert _has_any_marker(tmp_path, (".git",)) is True
    assert _has_any_marker(tmp_path, (".envrc",)) is False
    (tmp_path / ".envrc").write_text("")
    assert _has_any_marker(tmp_path, (".envrc",)) is True


def test_walk_markers_depth_and_stop_at_marker(tmp_path: Path) -> None:
    # root/a/.git  (depth1 project)  +  root/b/c/.git (depth2)  + root/d (no marker)
    (tmp_path / "a" / ".git").mkdir(parents=True)
    (tmp_path / "b" / "c" / ".git").mkdir(parents=True)
    (tmp_path / "d").mkdir()
    found: set[Path] = set()
    _walk_markers(tmp_path, depth=1, max_depth=2, markers=(".git",), found=found)
    names = {p.name for p in found}
    assert names == {"a", "c"}  # a(depth1), c(depth2); d 없음


def test_iter_union_projects_minus_excludes(tmp_path: Path) -> None:
    container = tmp_path / "dev"
    (container / "p1" / ".git").mkdir(parents=True)
    (container / "p2" / ".git").mkdir(parents=True)
    indiv = tmp_path / "work" / "x"
    (indiv / ".git").mkdir(parents=True)
    cfg = AnvycConfig(
        project_roots=[str(container)],
        projects=[str(indiv)],
        exclude_projects=[str(container / "p2")],
    )
    dirs = iter_project_dirs(cfg, markers=(".git",), max_depth=2)
    names = sorted(p.name for p in dirs)
    assert names == ["p1", "x"]  # p1(container) + x(individual) − p2(excluded)


def test_iter_individual_without_marker_skipped(tmp_path: Path) -> None:
    indiv = tmp_path / "no-marker"
    indiv.mkdir()
    cfg = AnvycConfig(project_roots=[], projects=[str(indiv)])
    assert iter_project_dirs(cfg, markers=(".git",)) == []
