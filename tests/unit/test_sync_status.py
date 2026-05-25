"""Unit tests for anvyc.core.sync (CP-6 1/3 — status)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from anvyc.core.sync import (
    ALL_KINDS,
    KIND_HEALTH_JSON,
    KIND_SNAPSHOT_META,
    REMOTE_MANIFEST_NAME,
    SCHEMA_VERSION,
    STATUS_DIFF,
    STATUS_LOCAL_ONLY,
    STATUS_REMOTE_ONLY,
    STATUS_SAME,
    SyncTargetManifest,
    compute_sync_status,
    load_remote_manifest,
    resolve_machine_id,
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


def _write_health(home: Path, date: str, content: str) -> None:
    d = home / ".config" / "cc-inspect" / "health"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{date}.json").write_text(content, encoding="utf-8")


def _write_snapshot_meta(home: Path, workspace: str, snap_id: str, content: str) -> None:
    d = home / "dev" / workspace / ".anvyc" / "snapshots" / snap_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(content, encoding="utf-8")


def test_resolve_machine_id_explicit() -> None:
    assert resolve_machine_id("custom-id") == "custom-id"


def test_resolve_machine_id_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANVYC_MACHINE_ID", "env-id")
    assert resolve_machine_id(None) == "env-id"


def test_resolve_machine_id_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANVYC_MACHINE_ID", raising=False)
    mid = resolve_machine_id(None)
    assert "@" in mid


def test_scan_local_manifest_empty(fake_home: Path, now_fixed: datetime) -> None:
    """home 에 아무것도 없을 때 빈 items."""
    m = scan_local_manifest(home=fake_home, machine_id="test", now=now_fixed)
    assert m.schema_version == SCHEMA_VERSION
    assert m.machine_id == "test"
    assert m.generated_at == "2026-05-25T10:00:00Z"
    assert m.items == []


def test_scan_local_manifest_health_only(fake_home: Path, now_fixed: datetime) -> None:
    _write_health(fake_home, "2026-05-25", '{"schema_version": 1}')
    _write_health(fake_home, "2026-05-24", '{"schema_version": 1}')
    m = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    assert len(m.items) == 2
    assert all(i.kind == KIND_HEALTH_JSON for i in m.items)
    paths = sorted(i.relative_path for i in m.items)
    assert paths == ["cc-inspect/health/2026-05-24.json", "cc-inspect/health/2026-05-25.json"]


def test_scan_local_manifest_snapshot_meta(fake_home: Path, now_fixed: datetime) -> None:
    _write_snapshot_meta(fake_home, "foo-project", "20260525T100000Z-a1b2c3", '{"schema_version": 1}')
    _write_snapshot_meta(fake_home, "bar-project", "20260525T110000Z-d4e5f6", '{"schema_version": 1}')
    m = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    snap_items = [i for i in m.items if i.kind == KIND_SNAPSHOT_META]
    assert len(snap_items) == 2
    paths = sorted(i.relative_path for i in snap_items)
    assert "anvyc/snapshots/bar-project-20260525T110000Z-d4e5f6/meta.json" in paths
    assert "anvyc/snapshots/foo-project-20260525T100000Z-a1b2c3/meta.json" in paths


def test_scan_local_manifest_mixed_kinds(fake_home: Path, now_fixed: datetime) -> None:
    _write_health(fake_home, "2026-05-25", "{}")
    _write_snapshot_meta(fake_home, "ws", "id1", "{}")
    m = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    kinds = sorted({i.kind for i in m.items})
    assert kinds == sorted(ALL_KINDS)


def test_scan_local_manifest_kinds_filter(fake_home: Path, now_fixed: datetime) -> None:
    _write_health(fake_home, "2026-05-25", "{}")
    _write_snapshot_meta(fake_home, "ws", "id1", "{}")
    m = scan_local_manifest(home=fake_home, machine_id="t", kinds=[KIND_HEALTH_JSON], now=now_fixed)
    assert all(i.kind == KIND_HEALTH_JSON for i in m.items)
    assert len(m.items) == 1


def test_scan_local_manifest_dev_root_override(tmp_path: Path, now_fixed: datetime) -> None:
    """dev_root override 로 workspace 위치 변경."""
    home = tmp_path / "h"
    dev = tmp_path / "alt-dev"
    home.mkdir()
    dev.mkdir()
    _write_snapshot_meta(home, "ws", "id1", "{}")  # 이건 home/dev 에 들어감 — dev_root override 시 미발견
    # override 한 dev_root 에 별도 workspace
    (dev / "alt-ws" / ".anvyc" / "snapshots" / "id2").mkdir(parents=True)
    (dev / "alt-ws" / ".anvyc" / "snapshots" / "id2" / "meta.json").write_text("{}", encoding="utf-8")
    m = scan_local_manifest(home=home, dev_root=dev, machine_id="t", now=now_fixed)
    paths = [i.relative_path for i in m.items if i.kind == KIND_SNAPSHOT_META]
    assert any("alt-ws" in p for p in paths)
    assert not any("/ws-" in p for p in paths)  # home/dev 의 ws 는 미포함


def test_scan_local_manifest_sha256_computed(fake_home: Path, now_fixed: datetime) -> None:
    _write_health(fake_home, "2026-05-25", "deterministic-payload")
    m = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    item = m.items[0]
    # SHA-256 of "deterministic-payload"
    import hashlib
    assert item.sha256 == hashlib.sha256(b"deterministic-payload").hexdigest()
    assert item.size == len("deterministic-payload")


def test_load_remote_manifest_missing(tmp_path: Path) -> None:
    """target 디렉터리에 manifest 파일 부재 → None."""
    assert load_remote_manifest(tmp_path) is None


def test_load_remote_manifest_corrupt(tmp_path: Path) -> None:
    (tmp_path / REMOTE_MANIFEST_NAME).write_text("{not valid", encoding="utf-8")
    assert load_remote_manifest(tmp_path) is None


def test_load_remote_manifest_version_mismatch(tmp_path: Path) -> None:
    (tmp_path / REMOTE_MANIFEST_NAME).write_text(
        json.dumps({"schema_version": 999, "machine_id": "x", "items": []}),
        encoding="utf-8",
    )
    assert load_remote_manifest(tmp_path) is None


def test_load_remote_manifest_valid(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "machine_id": "remote-m",
        "generated_at": "2026-05-24T00:00:00Z",
        "items": [
            {
                "kind": "health_json",
                "relative_path": "cc-inspect/health/2026-05-24.json",
                "size": 100,
                "sha256": "abc",
                "mtime": "2026-05-24T00:00:00Z",
            }
        ],
    }
    (tmp_path / REMOTE_MANIFEST_NAME).write_text(json.dumps(payload), encoding="utf-8")
    m = load_remote_manifest(tmp_path)
    assert m is not None
    assert m.machine_id == "remote-m"
    assert len(m.items) == 1
    assert m.items[0].sha256 == "abc"


def test_compute_sync_status_remote_missing(fake_home: Path, now_fixed: datetime) -> None:
    """remote=None → 모든 local 이 local_only."""
    _write_health(fake_home, "2026-05-25", "x")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    report = compute_sync_status(local, None, now=now_fixed)
    assert report.summary[STATUS_LOCAL_ONLY] == 1
    assert report.summary[STATUS_SAME] == 0
    assert report.summary[STATUS_REMOTE_ONLY] == 0
    assert report.summary[STATUS_DIFF] == 0
    assert report.diff_entries[0].status == STATUS_LOCAL_ONLY
    assert report.diff_entries[0].remote is None


def test_compute_sync_status_same(fake_home: Path, now_fixed: datetime) -> None:
    """same: local 과 remote 의 sha256 일치."""
    _write_health(fake_home, "2026-05-25", "identical-content")
    local = scan_local_manifest(home=fake_home, machine_id="local-m", now=now_fixed)
    # remote manifest 가 동일 sha256 entry 포함
    import hashlib
    same_sha = hashlib.sha256(b"identical-content").hexdigest()
    remote = SyncTargetManifest(
        schema_version=1,
        machine_id="remote-m",
        generated_at="2026-05-24T00:00:00Z",
        items=local.items.__class__([
            local.items[0].__class__(
                kind=KIND_HEALTH_JSON,
                relative_path="cc-inspect/health/2026-05-25.json",
                size=len("identical-content"),
                sha256=same_sha,
                mtime="2026-05-24T00:00:00Z",
            )
        ]),
    )
    report = compute_sync_status(local, remote, now=now_fixed)
    assert report.summary[STATUS_SAME] == 1
    assert report.summary[STATUS_DIFF] == 0


def test_compute_sync_status_diff(fake_home: Path, now_fixed: datetime) -> None:
    """diff: 동일 path 의 다른 sha256."""
    _write_health(fake_home, "2026-05-25", "local-content")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    remote = SyncTargetManifest(
        schema_version=1,
        machine_id="other",
        generated_at="x",
        items=[
            local.items[0].__class__(
                kind=KIND_HEALTH_JSON,
                relative_path="cc-inspect/health/2026-05-25.json",
                size=999,
                sha256="different-sha",
                mtime="x",
            )
        ],
    )
    report = compute_sync_status(local, remote, now=now_fixed)
    assert report.summary[STATUS_DIFF] == 1


def test_compute_sync_status_remote_only(fake_home: Path, now_fixed: datetime) -> None:
    """remote_only: local 에 없는 remote item."""
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    # local 은 비어있고 remote 만 1건
    from anvyc.core.sync import SyncItem
    remote = SyncTargetManifest(
        schema_version=1,
        machine_id="other",
        generated_at="x",
        items=[
            SyncItem(
                kind=KIND_HEALTH_JSON,
                relative_path="cc-inspect/health/2026-05-24.json",
                size=100,
                sha256="abc",
                mtime="x",
            )
        ],
    )
    report = compute_sync_status(local, remote, now=now_fixed)
    assert report.summary[STATUS_REMOTE_ONLY] == 1
    assert report.diff_entries[0].local is None


def test_compute_sync_status_mixed(fake_home: Path, now_fixed: datetime) -> None:
    """4 status 가 모두 나오는 시나리오."""
    import hashlib
    # local: same-file + diff-file + local-only
    _write_health(fake_home, "2026-05-25", "same-payload")
    _write_health(fake_home, "2026-05-24", "local-version")
    _write_health(fake_home, "2026-05-23", "local-only-payload")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)

    from anvyc.core.sync import SyncItem
    remote = SyncTargetManifest(
        schema_version=1,
        machine_id="other",
        generated_at="x",
        items=[
            # same as local "2026-05-25"
            SyncItem(KIND_HEALTH_JSON, "cc-inspect/health/2026-05-25.json", len("same-payload"),
                     hashlib.sha256(b"same-payload").hexdigest(), "x"),
            # diff vs local "2026-05-24" (different sha)
            SyncItem(KIND_HEALTH_JSON, "cc-inspect/health/2026-05-24.json", 999, "remote-sha", "x"),
            # remote_only
            SyncItem(KIND_HEALTH_JSON, "cc-inspect/health/2026-05-22.json", 100, "remote-only-sha", "x"),
        ],
    )
    report = compute_sync_status(local, remote, now=now_fixed)
    assert report.summary[STATUS_SAME] == 1
    assert report.summary[STATUS_DIFF] == 1
    assert report.summary[STATUS_LOCAL_ONLY] == 1
    assert report.summary[STATUS_REMOTE_ONLY] == 1


def test_compute_sync_status_to_dict_schema(fake_home: Path, now_fixed: datetime) -> None:
    """to_dict() 출력 schema 검증 (JSON 직렬화 용)."""
    _write_health(fake_home, "2026-05-25", "x")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    report = compute_sync_status(local, None, now=now_fixed)
    d = report.to_dict()
    assert d["schema_version"] == 1
    assert d["machine_id"] == "t"
    assert d["checked_at"] == "2026-05-25T10:00:00Z"
    summary = d["summary"]
    assert isinstance(summary, dict)
    assert set(summary) == {STATUS_SAME, STATUS_LOCAL_ONLY, STATUS_REMOTE_ONLY, STATUS_DIFF}
    diff_entries = d["diff_entries"]
    assert isinstance(diff_entries, list)
    assert len(diff_entries) == 1
    e = diff_entries[0]
    assert isinstance(e, dict)
    assert set(e) == {"relative_path", "status", "local", "remote"}
