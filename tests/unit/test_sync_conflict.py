"""Unit tests for anvyc.core.sync conflict resolution (CP-6 3/3)."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from anvyc.core.sync import (
    ALL_KEEP_CHOICES,
    KEEP_LOCAL,
    KEEP_REMOTE,
    REMOTE_MANIFEST_NAME,
    STATUS_DIFF,
    SyncConflictError,
    SyncError,
    list_conflicts,
    push_to_remote,
    resolve_conflict,
    scan_local_manifest,
)


@pytest.fixture
def now_fixed() -> datetime:
    return datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def remote_target(tmp_path: Path) -> Path:
    t = tmp_path / "remote"
    t.mkdir()
    return t


def _write_health(home: Path, date: str, content: str) -> None:
    d = home / ".config" / "cc-inspect" / "health"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{date}.json").write_text(content, encoding="utf-8")


def _setup_diff(fake_home: Path, remote_target: Path, now_fixed: datetime) -> str:
    """conflict scenario 셋업 — local/remote 같은 path 에 다른 본문.

    Returns: conflict 의 relative_path.
    """
    _write_health(fake_home, "2026-05-25", "local-version")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    push_to_remote(local, remote_target, home=fake_home, now=now_fixed)

    # remote 본문 + manifest 변경 → diff
    (remote_target / "cc-inspect/health/2026-05-25.json").write_text("remote-version", encoding="utf-8")
    data = json.loads((remote_target / REMOTE_MANIFEST_NAME).read_text())
    for item in data["items"]:
        if item["relative_path"] == "cc-inspect/health/2026-05-25.json":
            item["sha256"] = hashlib.sha256(b"remote-version").hexdigest()
            item["size"] = len("remote-version")
    (remote_target / REMOTE_MANIFEST_NAME).write_text(json.dumps(data))
    return "cc-inspect/health/2026-05-25.json"


# ===== list_conflicts =====

def test_list_conflicts_empty(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """conflict 없으면 빈 list."""
    _write_health(fake_home, "2026-05-25", "same")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    push_to_remote(local, remote_target, home=fake_home, now=now_fixed)
    assert list_conflicts(remote_target, home=fake_home, now=now_fixed) == []


def test_list_conflicts_filter_diff_only(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """diff entries 만 반환 — local_only / remote_only / same 은 제외."""
    # diff 1건 셋업
    _setup_diff(fake_home, remote_target, now_fixed)
    # + local_only (다른 날짜)
    _write_health(fake_home, "2026-05-26", "local-only")
    conflicts = list_conflicts(remote_target, home=fake_home, now=now_fixed)
    assert len(conflicts) == 1
    assert all(e.status == STATUS_DIFF for e in conflicts)
    assert conflicts[0].relative_path == "cc-inspect/health/2026-05-25.json"


def test_list_conflicts_no_remote_raises(fake_home: Path, tmp_path: Path) -> None:
    """remote manifest 부재 → SyncError."""
    with pytest.raises(SyncError, match="remote manifest 부재"):
        list_conflicts(tmp_path / "empty-remote", home=fake_home)


# ===== resolve_conflict — input validation =====

def test_resolve_invalid_keep(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """keep != local/remote → SyncConflictError."""
    rel = _setup_diff(fake_home, remote_target, now_fixed)
    with pytest.raises(SyncConflictError, match="invalid --keep"):
        resolve_conflict(remote_target, rel, keep="newer", home=fake_home)


def test_resolve_no_remote_raises(fake_home: Path, tmp_path: Path) -> None:
    with pytest.raises(SyncError, match="remote manifest 부재"):
        resolve_conflict(tmp_path / "x", "anything", keep=KEEP_LOCAL, home=fake_home)


def test_resolve_path_not_in_conflict_raises(
    fake_home: Path, remote_target: Path, now_fixed: datetime
) -> None:
    """conflict 없는 path → SyncConflictError."""
    _write_health(fake_home, "2026-05-25", "same")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    push_to_remote(local, remote_target, home=fake_home, now=now_fixed)
    with pytest.raises(SyncConflictError, match="no conflict"):
        resolve_conflict(
            remote_target,
            "cc-inspect/health/2026-05-25.json",
            keep=KEEP_LOCAL,
            home=fake_home,
        )


# ===== resolve_conflict — happy paths =====

def test_resolve_keep_local(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """keep=local → remote 본문이 local 로 overwrite + manifest 갱신."""
    rel = _setup_diff(fake_home, remote_target, now_fixed)
    result = resolve_conflict(
        remote_target, rel, keep=KEEP_LOCAL, home=fake_home, now=now_fixed
    )
    assert result.operation == "conflict-keep-local"
    assert result.items_copied == 1
    assert result.manifest_written is True
    # remote 본문이 local-version 으로 바뀜
    assert (remote_target / rel).read_text() == "local-version"
    # local 본문은 그대로
    assert (fake_home / ".config/cc-inspect/health/2026-05-25.json").read_text() == "local-version"
    # 해결 후 conflict 사라짐
    assert list_conflicts(remote_target, home=fake_home, now=now_fixed) == []


def test_resolve_keep_remote(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """keep=remote → local 본문이 remote 로 overwrite (manifest 무변)."""
    rel = _setup_diff(fake_home, remote_target, now_fixed)
    result = resolve_conflict(
        remote_target, rel, keep=KEEP_REMOTE, home=fake_home, now=now_fixed
    )
    assert result.operation == "conflict-keep-remote"
    assert result.items_copied == 1
    assert result.manifest_written is False  # pull-one 은 remote manifest 변경 안 함
    # local 본문이 remote-version 으로 바뀜
    assert (fake_home / ".config/cc-inspect/health/2026-05-25.json").read_text() == "remote-version"
    # remote 본문 그대로
    assert (remote_target / rel).read_text() == "remote-version"
    # 해결 후 conflict 사라짐
    assert list_conflicts(remote_target, home=fake_home, now=now_fixed) == []


def test_resolve_keep_constants() -> None:
    """ALL_KEEP_CHOICES 가 local + remote 만."""
    assert set(ALL_KEEP_CHOICES) == {KEEP_LOCAL, KEEP_REMOTE}


# ===== snapshot_meta conflict resolution (역매핑 검증) =====

def test_resolve_keep_local_snapshot_meta(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """snapshot_meta entry 의 conflict resolve — 역매핑 path 정확."""
    # local snapshot meta + push
    snap_dir = fake_home / "dev" / "myws" / ".anvyc" / "snapshots" / "20260525T100000Z-abcdef"
    snap_dir.mkdir(parents=True)
    (snap_dir / "meta.json").write_text("local-snap", encoding="utf-8")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    push_to_remote(local, remote_target, home=fake_home, now=now_fixed)

    # remote 측 본문 변경 + manifest sha 갱신 (diff 발생)
    rel = "anvyc/snapshots/myws-20260525T100000Z-abcdef/meta.json"
    (remote_target / rel).write_text("remote-snap-changed", encoding="utf-8")
    data = json.loads((remote_target / REMOTE_MANIFEST_NAME).read_text())
    for item in data["items"]:
        if item["relative_path"] == rel:
            item["sha256"] = hashlib.sha256(b"remote-snap-changed").hexdigest()
            item["size"] = len("remote-snap-changed")
    (remote_target / REMOTE_MANIFEST_NAME).write_text(json.dumps(data))

    # keep=local → remote 가 local 으로 overwrite
    result = resolve_conflict(remote_target, rel, keep=KEEP_LOCAL, home=fake_home, now=now_fixed)
    assert result.operation == "conflict-keep-local"
    assert (remote_target / rel).read_text() == "local-snap"
    # local 도 그대로
    assert (snap_dir / "meta.json").read_text() == "local-snap"
