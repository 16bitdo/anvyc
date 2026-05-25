"""Unit tests for anvyc.core.snapshot list/diff (CP-4 2/3)."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from anvyc.core.snapshot import (
    SnapshotDiffError,
    SnapshotNotFoundError,
    create_snapshot,
    diff_snapshot,
    get_snapshot,
    list_snapshots,
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


def test_list_empty(tmp_path: Path) -> None:
    """snapshots/ 디렉터리 부재 → 빈 list."""
    assert list_snapshots(tmp_path / "anvyc") == []


def test_list_single_snapshot(git_repo: Path, tmp_path: Path) -> None:
    anvyc_dir = tmp_path / "anvyc"
    meta = create_snapshot(git_repo, anvyc_dir, label="solo")
    result = list_snapshots(anvyc_dir)
    assert len(result) == 1
    assert result[0].id == meta.id
    assert result[0].label == "solo"


def test_list_sorts_by_created_at_desc(git_repo: Path, tmp_path: Path) -> None:
    """created_at 내림차순 정렬."""
    anvyc_dir = tmp_path / "anvyc"
    m1 = create_snapshot(git_repo, anvyc_dir, label="older")
    time.sleep(1.1)  # ISO 초 단위 분리 (CP-3 학습 L8 적용)
    m2 = create_snapshot(git_repo, anvyc_dir, label="newer")
    time.sleep(1.1)
    m3 = create_snapshot(git_repo, anvyc_dir, label="newest")

    result = list_snapshots(anvyc_dir)
    assert [m.id for m in result] == [m3.id, m2.id, m1.id]
    assert [m.label for m in result] == ["newest", "newer", "older"]


def test_list_skips_corrupt_meta(git_repo: Path, tmp_path: Path) -> None:
    """손상된 meta.json 은 silently skip."""
    anvyc_dir = tmp_path / "anvyc"
    m = create_snapshot(git_repo, anvyc_dir, label="valid")

    # 손상 entry 1건 추가
    bad_dir = anvyc_dir / "snapshots" / "20260524T010000Z-deadbe"
    bad_dir.mkdir(parents=True)
    (bad_dir / "meta.json").write_text("{not valid json", encoding="utf-8")

    # version 미스매치 1건 추가
    v999_dir = anvyc_dir / "snapshots" / "20260524T010100Z-cafe00"
    v999_dir.mkdir(parents=True)
    (v999_dir / "meta.json").write_text(json.dumps({"schema_version": 999, "id": "x"}), encoding="utf-8")

    result = list_snapshots(anvyc_dir)
    assert len(result) == 1
    assert result[0].id == m.id


def test_list_skips_non_dir_entries(git_repo: Path, tmp_path: Path) -> None:
    """snapshots/ 내 파일 entry (디렉터리 아닌) skip."""
    anvyc_dir = tmp_path / "anvyc"
    m = create_snapshot(git_repo, anvyc_dir)
    (anvyc_dir / "snapshots" / "stray.txt").write_text("noise", encoding="utf-8")
    assert len(list_snapshots(anvyc_dir)) == 1
    assert list_snapshots(anvyc_dir)[0].id == m.id


def test_get_snapshot_missing_returns_none(tmp_path: Path) -> None:
    assert get_snapshot(tmp_path / "anvyc", "nonexistent") is None


def test_diff_snapshot_against_current(git_repo: Path, tmp_path: Path) -> None:
    """snapshot 시점의 stash vs 현재 working tree — diff 본문 반환."""
    anvyc_dir = tmp_path / "anvyc"

    # snapshot 시점: README 수정 + 신규 파일
    (git_repo / "README").write_text("v1\n", encoding="utf-8")
    (git_repo / "new.txt").write_text("snap-content\n", encoding="utf-8")
    m = create_snapshot(git_repo, anvyc_dir)
    assert m.git_stash_sha is not None

    # snapshot 이후 working tree 변경 (다른 수정)
    (git_repo / "README").write_text("v2\n", encoding="utf-8")

    diff_text = diff_snapshot(git_repo, anvyc_dir, m.id)
    # diff 가 비어있지 않고 변경 마커 포함
    assert "diff --git" in diff_text or "README" in diff_text


def test_diff_snapshot_working_clean_message(git_repo: Path, tmp_path: Path) -> None:
    """working_clean=true snapshot 은 diff 대상 없음 안내."""
    anvyc_dir = tmp_path / "anvyc"
    m = create_snapshot(git_repo, anvyc_dir, label="clean-marker")
    assert m.working_clean is True

    text = diff_snapshot(git_repo, anvyc_dir, m.id)
    assert "working_clean=true" in text
    assert m.id in text


def test_diff_snapshot_between_two(git_repo: Path, tmp_path: Path) -> None:
    """두 snapshot 간 diff (양쪽 모두 stash 있는 경우)."""
    anvyc_dir = tmp_path / "anvyc"

    (git_repo / "README").write_text("rev-A\n", encoding="utf-8")
    m_a = create_snapshot(git_repo, anvyc_dir, label="A")
    time.sleep(1.1)
    (git_repo / "README").write_text("rev-B\n", encoding="utf-8")
    m_b = create_snapshot(git_repo, anvyc_dir, label="B")

    assert m_a.git_stash_sha and m_b.git_stash_sha
    diff_text = diff_snapshot(git_repo, anvyc_dir, m_a.id, against=m_b.id)
    # 양 snapshot 간 README 차이가 보여야 함
    assert "README" in diff_text


def test_diff_snapshot_against_clean_message(git_repo: Path, tmp_path: Path) -> None:
    """한쪽이 working_clean=true 면 안내 메시지."""
    anvyc_dir = tmp_path / "anvyc"
    m_clean = create_snapshot(git_repo, anvyc_dir, label="clean")
    (git_repo / "README").write_text("dirty\n", encoding="utf-8")
    m_dirty = create_snapshot(git_repo, anvyc_dir, label="dirty")

    text = diff_snapshot(git_repo, anvyc_dir, m_dirty.id, against=m_clean.id)
    assert "working_clean=true" in text


def test_diff_snapshot_not_found_raises(tmp_path: Path) -> None:
    """존재하지 않는 id → SnapshotNotFoundError."""
    with pytest.raises(SnapshotNotFoundError, match="snapshot not found: ghost"):
        diff_snapshot(tmp_path, tmp_path / "anvyc", "ghost")


def test_diff_snapshot_against_not_found(git_repo: Path, tmp_path: Path) -> None:
    """against id 부재도 SnapshotNotFoundError."""
    anvyc_dir = tmp_path / "anvyc"
    (git_repo / "README").write_text("x\n", encoding="utf-8")
    m = create_snapshot(git_repo, anvyc_dir)
    with pytest.raises(SnapshotNotFoundError, match="snapshot not found: nope"):
        diff_snapshot(git_repo, anvyc_dir, m.id, against="nope")


def test_diff_snapshot_unreachable_stash_raises(git_repo: Path, tmp_path: Path) -> None:
    """git ref 가 삭제되면 SnapshotDiffError."""
    anvyc_dir = tmp_path / "anvyc"
    (git_repo / "README").write_text("x\n", encoding="utf-8")
    m = create_snapshot(git_repo, anvyc_dir)
    assert m.git_stash_ref is not None
    # ref 삭제 + GC 로 stash sha unreachable 시뮬레이션
    _run(git_repo, "update-ref", "-d", m.git_stash_ref)
    _run(git_repo, "reflog", "expire", "--expire=now", "--all")
    _run(git_repo, "gc", "--prune=now", "--quiet")
    with pytest.raises(SnapshotDiffError):
        diff_snapshot(git_repo, anvyc_dir, m.id)
