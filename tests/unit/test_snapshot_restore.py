"""Unit tests for anvyc.core.snapshot restore (CP-4 3/3)."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from anvyc.core.snapshot import (
    SnapshotNotFoundError,
    SnapshotRestoreError,
    create_snapshot,
    list_snapshots,
    plan_restore,
    restore_snapshot,
)


def _run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q", "-b", "main")
    _run(repo, "config", "user.email", "t@t")
    _run(repo, "config", "user.name", "test")
    (repo / "README").write_text("init\n", encoding="utf-8")
    _run(repo, "add", "README")
    _run(repo, "commit", "-q", "-m", "init")
    return repo


def test_plan_restore_not_found(tmp_path: Path) -> None:
    with pytest.raises(SnapshotNotFoundError):
        plan_restore(tmp_path, tmp_path / "anvyc", "ghost")


def test_plan_restore_clean_marker_warns(git_repo: Path, tmp_path: Path) -> None:
    """clean marker snapshot 의 plan 은 'no apply' 경고 + cmd 비어 있음."""
    anvyc_dir = tmp_path / "anvyc"
    m = create_snapshot(git_repo, anvyc_dir, label="clean")
    plan = plan_restore(git_repo, anvyc_dir, m.id)
    assert plan.target_working_clean is True
    assert plan.git_apply_command == []
    assert plan.will_create_pre_restore_snapshot is False
    assert any("working_clean=true" in w for w in plan.warnings)


def test_plan_restore_with_stash(git_repo: Path, tmp_path: Path) -> None:
    """stash 있는 snapshot 의 plan — git apply 명령 + pre-restore=yes."""
    anvyc_dir = tmp_path / "anvyc"
    (git_repo / "README").write_text("v1\n", encoding="utf-8")
    m = create_snapshot(git_repo, anvyc_dir, label="v1")
    plan = plan_restore(git_repo, anvyc_dir, m.id)
    assert plan.target_stash_sha is not None
    assert plan.will_create_pre_restore_snapshot is True
    assert plan.git_apply_command[:3] == ["git", "-C", str(git_repo)]
    assert "stash" in plan.git_apply_command
    assert "apply" in plan.git_apply_command


def test_plan_restore_warns_on_branch_mismatch(git_repo: Path, tmp_path: Path) -> None:
    """target 과 현재 branch 불일치 시 warning."""
    anvyc_dir = tmp_path / "anvyc"
    (git_repo / "README").write_text("on-main\n", encoding="utf-8")
    m = create_snapshot(git_repo, anvyc_dir, label="on-main-snap")

    _run(git_repo, "checkout", "-b", "other")
    plan = plan_restore(git_repo, anvyc_dir, m.id)
    assert any("branch 불일치" in w for w in plan.warnings)


def test_plan_restore_warns_on_uncommitted(git_repo: Path, tmp_path: Path) -> None:
    """현재 uncommitted 가 있으면 plan warning."""
    anvyc_dir = tmp_path / "anvyc"
    m = create_snapshot(git_repo, anvyc_dir)
    (git_repo / "new.txt").write_text("dirty\n", encoding="utf-8")
    plan = plan_restore(git_repo, anvyc_dir, m.id)
    assert any("working tree 에" in w and "변경" in w for w in plan.warnings)


def test_restore_snapshot_clean_marker_noop(git_repo: Path, tmp_path: Path) -> None:
    """clean marker 의 restore 는 no-op (applied=False)."""
    anvyc_dir = tmp_path / "anvyc"
    m = create_snapshot(git_repo, anvyc_dir, label="clean")
    result = restore_snapshot(git_repo, anvyc_dir, m.id)
    assert result.applied is False
    assert result.pre_restore_snapshot_id is None
    assert result.target_id == m.id


def test_restore_snapshot_applies_stash(git_repo: Path, tmp_path: Path) -> None:
    """stash 있는 snapshot — restore 가 working tree 에 변경 apply + pre-restore 생성."""
    anvyc_dir = tmp_path / "anvyc"
    (git_repo / "README").write_text("captured-content\n", encoding="utf-8")
    m = create_snapshot(git_repo, anvyc_dir, label="captured")
    # snapshot 후 working tree 를 clean 으로 (snapshot 변경분이 stash 에만 있게)
    _run(git_repo, "checkout", "--", "README")
    assert (git_repo / "README").read_text() == "init\n"

    time.sleep(1.1)  # pre-restore 의 id 가 m 와 충돌 안 하게
    result = restore_snapshot(git_repo, anvyc_dir, m.id)
    assert result.applied is True
    assert result.pre_restore_snapshot_id is not None
    assert (git_repo / "README").read_text() == "captured-content\n"

    # pre-restore snapshot 이 실제 list 에 등장하는지
    snaps = list_snapshots(anvyc_dir)
    pre_labels = [s.label for s in snaps if s.id == result.pre_restore_snapshot_id]
    assert pre_labels == [f"pre-restore-{m.id}"]


def test_restore_snapshot_not_found(tmp_path: Path) -> None:
    with pytest.raises(SnapshotNotFoundError):
        restore_snapshot(tmp_path, tmp_path / "anvyc", "ghost")


def test_restore_snapshot_conflict_raises(git_repo: Path, tmp_path: Path) -> None:
    """stash apply 가 conflict 일 때 SnapshotRestoreError + pre-restore id 안내."""
    anvyc_dir = tmp_path / "anvyc"

    # snapshot 시점: README 를 "snap-version" 으로 수정 → stash 에 캡쳐
    (git_repo / "README").write_text("snap-version\n", encoding="utf-8")
    m = create_snapshot(git_repo, anvyc_dir, label="snap")
    # working tree 복원 후, README 를 다른 값으로 commit → apply 시 conflict
    _run(git_repo, "checkout", "--", "README")
    (git_repo / "README").write_text("conflicting-committed\n", encoding="utf-8")
    _run(git_repo, "add", "README")
    _run(git_repo, "commit", "-q", "-m", "conflict-setup")

    time.sleep(1.1)
    with pytest.raises(SnapshotRestoreError) as excinfo:
        restore_snapshot(git_repo, anvyc_dir, m.id)
    # pre-restore snapshot id 가 message 에 포함되어야 함 (회복 채널 안내)
    assert "pre-restore snapshot" in str(excinfo.value)

    # conflict 가 발생해도 pre-restore snapshot 은 이미 생성됨
    snaps = list_snapshots(anvyc_dir)
    pre_labels = [s.label for s in snaps if s.label and s.label.startswith("pre-restore-")]
    assert len(pre_labels) == 1


def test_restore_unreachable_stash_raises(git_repo: Path, tmp_path: Path) -> None:
    """target stash ref 가 GC 된 경우 SnapshotRestoreError (pre-restore 는 생성됨)."""
    anvyc_dir = tmp_path / "anvyc"
    (git_repo / "README").write_text("x\n", encoding="utf-8")
    m = create_snapshot(git_repo, anvyc_dir)
    assert m.git_stash_ref is not None
    _run(git_repo, "update-ref", "-d", m.git_stash_ref)
    _run(git_repo, "reflog", "expire", "--expire=now", "--all")
    _run(git_repo, "gc", "--prune=now", "--quiet")

    time.sleep(1.1)
    with pytest.raises(SnapshotRestoreError):
        restore_snapshot(git_repo, anvyc_dir, m.id)
