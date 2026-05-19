"""project_discovery 단위 테스트 (P2, v0.8.1)."""
from __future__ import annotations

from pathlib import Path

from anvyc.core.project_discovery import (
    DEFAULT_ROOTS,
    PROJECT_MARKERS,
    discover_projects,
)


def _mkproj(root: Path, name: str, marker: str = ".git") -> Path:
    """root 아래 marker 보유 project 생성."""
    proj = root / name
    proj.mkdir(parents=True, exist_ok=True)
    if marker == ".git":
        (proj / ".git").mkdir(exist_ok=True)
        (proj / ".git" / "config").write_text("")
    elif marker == "Pulumi.yaml":
        (proj / "Pulumi.yaml").write_text("name: t\nruntime: python\n")
    return proj


def test_default_constants() -> None:
    assert "~/Documents" in DEFAULT_ROOTS
    assert ".git" in PROJECT_MARKERS
    assert "Pulumi.yaml" in PROJECT_MARKERS


def test_discover_finds_git_and_pulumi(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    _mkproj(root, "git-proj", marker=".git")
    _mkproj(root, "pulumi-proj", marker="Pulumi.yaml")
    (root / "plain-dir").mkdir()  # marker 없음 — skip

    out = discover_projects([str(root)])
    names = sorted(p.name for p in out)
    assert names == ["git-proj", "pulumi-proj"]


def test_discover_skip_unmarked_directories(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "no-marker").mkdir()
    (root / "no-marker" / "README.md").write_text("# x")
    out = discover_projects([str(root)])
    assert out == []


def test_multi_root(tmp_path: Path) -> None:
    r1 = tmp_path / "a"
    r2 = tmp_path / "b"
    r1.mkdir()
    r2.mkdir()
    _mkproj(r1, "proj1", ".git")
    _mkproj(r2, "proj2", ".git")

    out = discover_projects([str(r1), str(r2)])
    assert {p.name for p in out} == {"proj1", "proj2"}


def test_missing_root_silent(tmp_path: Path) -> None:
    out = discover_projects([str(tmp_path / "nonexistent")])
    assert out == []


def test_deep_nesting_obeys_max_depth(tmp_path: Path) -> None:
    """root/sub/proj 가 max_depth=1 이면 발견 안 됨."""
    root = tmp_path / "docs"
    root.mkdir()
    sub = root / "sub"
    sub.mkdir()
    _mkproj(sub, "deep-proj", ".git")

    # max_depth=1 → root/sub 까지 못 들어감
    out = discover_projects([str(root)], max_depth=1)
    assert out == []
    # max_depth=2 → root/sub 내부도 scan
    out2 = discover_projects([str(root)], max_depth=2)
    assert any(p.name == "deep-proj" for p in out2)


def test_symlinks_not_followed(tmp_path: Path) -> None:
    """symlink 디렉터리는 alias 가능 → skip."""
    import os
    root = tmp_path / "docs"
    root.mkdir()
    real = _mkproj(root, "real-proj", ".git")
    (root / "alias").symlink_to(real, target_is_directory=True)

    out = discover_projects([str(root)])
    names = [p.name for p in out]
    # real-proj 만 발견, alias 는 symlink 라 skip
    assert "real-proj" in names
    assert "alias" not in names


def test_result_sorted_alphabetical(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    _mkproj(root, "zebra", ".git")
    _mkproj(root, "apple", ".git")
    _mkproj(root, "mango", ".git")

    out = discover_projects([str(root)])
    assert [p.name for p in out] == ["apple", "mango", "zebra"]
