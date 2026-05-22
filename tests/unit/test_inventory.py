"""ManagedFile dataclass — relpath / symlink_target 기본값."""
from __future__ import annotations

from pathlib import Path

from anvyc.core.inventory import ManagedFile


def test_relpath_defaults_to_source_name(tmp_path: Path) -> None:
    src = tmp_path / "file.txt"
    src.write_text("x")
    mf = ManagedFile(tool="shell", source_path=src, target_path=Path("~/file.txt"))
    assert mf.relpath == "file.txt"


def test_explicit_relpath_preserved(tmp_path: Path) -> None:
    src = tmp_path / "hooks/script.sh"
    src.parent.mkdir(parents=True)
    src.write_text("#!/bin/sh\n")
    mf = ManagedFile(
        tool="claude",
        source_path=src,
        target_path=Path("~/.claude/hooks/script.sh"),
        relpath="hooks/script.sh",
    )
    assert mf.relpath == "hooks/script.sh"


def test_symlink_target_default_none(tmp_path: Path) -> None:
    src = tmp_path / "file"
    src.write_text("x")
    mf = ManagedFile(tool="t", source_path=src, target_path=Path("~/x"))
    assert mf.symlink_target is None


def test_symlink_target_explicit(tmp_path: Path) -> None:
    src = tmp_path / "link"
    mf = ManagedFile(
        tool="cursor",
        source_path=src,
        target_path=Path("~/.cursor/link"),
        symlink_target="/Users/x/elsewhere",
    )
    assert mf.symlink_target == "/Users/x/elsewhere"
