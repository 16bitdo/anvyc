"""backup → status → diff 핵심 흐름."""
from __future__ import annotations

from pathlib import Path

from anvyc.core.backup import run_backup
from anvyc.core.diff import compute_diff
from anvyc.core.status import compute_status


def test_backup_creates_files_and_metadata(isolated_env: dict[str, Path]) -> None:
    root = isolated_env["root"]
    config = isolated_env["config"]
    result = run_backup(root=root, config_path=config)
    assert result.backup_dir.exists()
    assert (result.backup_dir / "metadata.json").is_file()
    # zshrc + zprofile 둘 다 백업됐는지
    assert (result.backup_dir / "shell" / "fake.zshrc").is_file()
    assert (result.backup_dir / "shell" / "fake.zprofile").is_file()


def test_current_symlink_updates(isolated_env: dict[str, Path]) -> None:
    root = isolated_env["root"]
    result = run_backup(root=root, config_path=isolated_env["config"])
    cur = root / "current"
    assert cur.is_symlink()
    assert cur.resolve() == result.backup_dir.resolve()


def test_status_unchanged_after_backup(isolated_env: dict[str, Path]) -> None:
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    report = compute_status(isolated_env["root"])
    counts = report.counts()
    assert counts.get("modified", 0) == 0
    assert counts.get("missing", 0) == 0
    assert counts.get("unchanged", 0) >= 2


def test_status_detects_modified(isolated_env: dict[str, Path]) -> None:
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    isolated_env["zshrc"].write_text("alias modified=99\n")
    report = compute_status(isolated_env["root"])
    counts = report.counts()
    assert counts["modified"] >= 1


def test_status_detects_missing(isolated_env: dict[str, Path]) -> None:
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    isolated_env["zshrc"].unlink()
    report = compute_status(isolated_env["root"])
    assert report.counts()["missing"] >= 1


def test_diff_returns_unified_text(isolated_env: dict[str, Path]) -> None:
    result = run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    isolated_env["zshrc"].write_text("alias x=1\nalias modified=2\n")
    src = result.backup_dir / "shell" / "fake.zshrc"
    d = compute_diff(src, isolated_env["zshrc"])
    assert d.has_change
    assert "+alias modified=2" in d.unified
