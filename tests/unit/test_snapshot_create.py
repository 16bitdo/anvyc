"""Unit tests for anvyc.core.snapshot (CP-4 1/3 create)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from anvyc.core.snapshot import (
    SCHEMA_VERSION,
    SNAPSHOTS_SUBDIR,
    STASH_REF_PREFIX,
    SnapshotMeta,
    create_snapshot,
)


def _run(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """초기 commit 1건 + clean working tree 의 git repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q", "-b", "main")
    _run(repo, "config", "user.email", "t@t")
    _run(repo, "config", "user.name", "test")
    (repo / "README").write_text("init\n", encoding="utf-8")
    _run(repo, "add", "README")
    _run(repo, "commit", "-q", "-m", "init")
    return repo


def test_create_snapshot_clean_tree(git_repo: Path, tmp_path: Path) -> None:
    """working tree 가 clean 이어도 marker snapshot 생성."""
    anvyc_dir = tmp_path / "anvyc"
    meta = create_snapshot(git_repo, anvyc_dir, label="clean-marker")

    assert isinstance(meta, SnapshotMeta)
    assert meta.schema_version == SCHEMA_VERSION
    assert meta.label == "clean-marker"
    assert meta.git_branch == "main"
    assert meta.uncommitted_count == 0
    assert meta.working_clean is True
    assert meta.git_stash_ref is None  # nothing to stash
    assert meta.git_stash_sha is None

    # meta.json 저장 확인
    meta_path = anvyc_dir / SNAPSHOTS_SUBDIR / meta.id / "meta.json"
    assert meta_path.is_file()
    saved = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved["id"] == meta.id
    assert saved["working_clean"] is True


def test_create_snapshot_with_uncommitted(git_repo: Path, tmp_path: Path) -> None:
    """uncommitted 변경 + untracked 파일 모두 capture — stash anchor 생성."""
    # tracked 수정
    (git_repo / "README").write_text("modified\n", encoding="utf-8")
    # untracked 신규
    (git_repo / "new.txt").write_text("untracked\n", encoding="utf-8")

    anvyc_dir = tmp_path / "anvyc"
    meta = create_snapshot(git_repo, anvyc_dir, label="before-refactor")

    assert meta.label == "before-refactor"
    assert meta.uncommitted_count >= 1  # at least README
    assert meta.working_clean is False
    assert meta.git_stash_ref is not None
    assert meta.git_stash_ref.startswith(STASH_REF_PREFIX)
    assert meta.git_stash_sha is not None
    assert len(meta.git_stash_sha) == 40  # SHA-1

    # ref 가 실제 존재 + 같은 sha 가리키는지 (anchor 동작)
    ref_sha = _run(git_repo, "rev-parse", meta.git_stash_ref)
    assert ref_sha == meta.git_stash_sha

    # working tree 가 영향 안 받았는지 (non-disruptive)
    status = _run(git_repo, "status", "--porcelain")
    assert "README" in status  # tracked 수정 여전
    assert "new.txt" in status  # untracked 여전


def test_create_snapshot_session_id_from_env(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """env 의 CLAUDE_SESSION_ID 가 meta 에 captured."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "session-abc-123")
    anvyc_dir = tmp_path / "anvyc"
    meta = create_snapshot(git_repo, anvyc_dir)
    assert meta.claude_session_id == "session-abc-123"


def test_create_snapshot_session_id_explicit_overrides_env(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """명시 session_id 가 env 보다 우선."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "from-env")
    anvyc_dir = tmp_path / "anvyc"
    meta = create_snapshot(git_repo, anvyc_dir, session_id="from-cli")
    assert meta.claude_session_id == "from-cli"


def test_create_snapshot_unique_id_per_call(git_repo: Path, tmp_path: Path) -> None:
    """연속 호출 시 id 가 unique (timestamp + random hex 조합)."""
    anvyc_dir = tmp_path / "anvyc"
    m1 = create_snapshot(git_repo, anvyc_dir)
    m2 = create_snapshot(git_repo, anvyc_dir)
    assert m1.id != m2.id
    assert (anvyc_dir / SNAPSHOTS_SUBDIR / m1.id / "meta.json").is_file()
    assert (anvyc_dir / SNAPSHOTS_SUBDIR / m2.id / "meta.json").is_file()


def test_create_snapshot_detached_head(git_repo: Path, tmp_path: Path) -> None:
    """detached HEAD 시 branch 필드에 sha 가 들어감."""
    head_sha = _run(git_repo, "rev-parse", "HEAD")
    _run(git_repo, "checkout", "--detach", head_sha)
    anvyc_dir = tmp_path / "anvyc"
    meta = create_snapshot(git_repo, anvyc_dir)
    assert meta.git_branch == head_sha


def test_create_snapshot_non_git_raises(tmp_path: Path) -> None:
    """git repo 가 아니면 ValueError."""
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    anvyc_dir = tmp_path / "anvyc"
    with pytest.raises(ValueError, match="not a git working tree"):
        create_snapshot(not_a_repo, anvyc_dir)


def test_meta_schema_keys(git_repo: Path, tmp_path: Path) -> None:
    """meta.json 의 key 집합이 v1 스키마와 일치 (후속 PR 의 입력 contract)."""
    anvyc_dir = tmp_path / "anvyc"
    meta = create_snapshot(git_repo, anvyc_dir, label="schema-check")
    meta_path = anvyc_dir / SNAPSHOTS_SUBDIR / meta.id / "meta.json"
    saved = json.loads(meta_path.read_text(encoding="utf-8"))
    expected_keys = {
        "schema_version",
        "id",
        "label",
        "claude_session_id",
        "git_branch",
        "git_stash_ref",
        "git_stash_sha",
        "created_at",
        "uncommitted_count",
        "working_clean",
    }
    assert set(saved.keys()) == expected_keys
    assert saved["schema_version"] == 1


def test_create_snapshot_captures_untracked_files(git_repo: Path, tmp_path: Path) -> None:
    """untracked 파일도 stash 에 포함되어야 함 — fix for live-demo bug.

    `git stash create` 는 untracked 를 캡쳐 안 함; `git stash push -u` 가 필요.
    본 테스트는 _capture_stash 의 push -u + pop --index 접근법을 검증.
    """
    # tracked 수정 + untracked 신규
    (git_repo / "README").write_text("modified-tracked\n", encoding="utf-8")
    (git_repo / "new-untracked.txt").write_text("untracked-payload\n", encoding="utf-8")

    anvyc_dir = tmp_path / "anvyc"
    meta = create_snapshot(git_repo, anvyc_dir, label="with-untracked")
    assert meta.git_stash_sha is not None
    assert meta.git_stash_ref is not None

    # working tree 무영향 — push + pop --index 후에도 변경 보존
    assert (git_repo / "README").read_text() == "modified-tracked\n"
    assert (git_repo / "new-untracked.txt").read_text() == "untracked-payload\n"

    # stash 가 untracked 도 capture 했는지 — apply 시뮬레이션
    # working tree 를 initial 상태로 reset + untracked 삭제
    _run(git_repo, "checkout", "--", "README")
    (git_repo / "new-untracked.txt").unlink()
    assert (git_repo / "README").read_text() == "init\n"
    assert not (git_repo / "new-untracked.txt").exists()

    # anchored ref 로 stash apply → tracked + untracked 모두 복원되어야 함
    _run(git_repo, "stash", "apply", meta.git_stash_ref)
    assert (git_repo / "README").read_text() == "modified-tracked\n"
    assert (git_repo / "new-untracked.txt").read_text() == "untracked-payload\n"


def test_create_snapshot_untracked_only_no_tracked_changes(
    git_repo: Path, tmp_path: Path
) -> None:
    """tracked 변경 없이 untracked 만 있는 경우도 capture 되어야 함."""
    (git_repo / "only-untracked.txt").write_text("only", encoding="utf-8")
    anvyc_dir = tmp_path / "anvyc"
    meta = create_snapshot(git_repo, anvyc_dir, label="untracked-only")
    assert meta.working_clean is False
    assert meta.uncommitted_count >= 1
    assert meta.git_stash_sha is not None  # untracked 만 있어도 stash 생성

    # apply 시 복원
    (git_repo / "only-untracked.txt").unlink()
    assert meta.git_stash_ref is not None
    _run(git_repo, "stash", "apply", meta.git_stash_ref)
    assert (git_repo / "only-untracked.txt").read_text() == "only"
