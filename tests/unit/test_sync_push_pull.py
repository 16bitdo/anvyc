"""Unit tests for anvyc.core.sync push/pull (CP-6 2/3)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from anvyc.core.sync import (
    KIND_ACCOUNT_BINDINGS,
    KIND_HEALTH_JSON,
    KIND_SNAPSHOT_META,
    REMOTE_MANIFEST_NAME,
    SyncError,
    SyncItem,
    SyncTargetManifest,
    load_remote_manifest,
    pull_to_local,
    push_to_remote,
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


def _write_snapshot_meta(home: Path, workspace: str, snap_id: str, content: str) -> None:
    d = home / "dev" / workspace / ".anvyc" / "snapshots" / snap_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(content, encoding="utf-8")


def _write_account_bindings(home: Path, hostname: str, content: str) -> None:
    d = home / ".config" / "anvyc" / "accounts"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"bindings.{hostname}.yaml").write_text(content, encoding="utf-8")


# ===== push =====

def test_push_local_only_copies_files(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """local 만 있는 entries 가 remote 로 copy + manifest 작성."""
    _write_health(fake_home, "2026-05-25", "hello-world")
    _write_snapshot_meta(fake_home, "ws", "20260525T100000Z-a1b2c3", '{"k":"v"}')
    local = scan_local_manifest(home=fake_home, machine_id="src-m", now=now_fixed)

    result = push_to_remote(local, remote_target, home=fake_home, now=now_fixed)
    assert result.operation == "push"
    assert result.items_copied == 2
    assert result.items_skipped_conflict == 0
    assert result.items_failed == 0
    assert result.manifest_written is True

    # 실 파일이 remote 에 있는지
    assert (remote_target / "cc-inspect/health/2026-05-25.json").read_text() == "hello-world"
    snap_path = remote_target / "anvyc/snapshots/ws-20260525T100000Z-a1b2c3/meta.json"
    assert snap_path.read_text() == '{"k":"v"}'

    # remote manifest 가 v1 schema 로 작성됐는지
    m = load_remote_manifest(remote_target)
    assert m is not None
    assert m.schema_version == 1
    assert m.machine_id == "src-m"
    assert len(m.items) == 2


def test_push_same_skipped(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """이미 동일 sha256 인 entries 는 skip (copy 안 함)."""
    _write_health(fake_home, "2026-05-25", "identical")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)

    # 첫 push
    push_to_remote(local, remote_target, home=fake_home, now=now_fixed)
    # 두 번째 push — same
    result = push_to_remote(local, remote_target, home=fake_home, now=now_fixed)
    assert result.items_copied == 0
    assert result.items_skipped_same == 1
    assert result.items_skipped_conflict == 0


def test_push_diff_skip_without_force(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """conflict (sha256 불일치) 시 force 없으면 skip."""
    _write_health(fake_home, "2026-05-25", "local-content")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)

    # remote 에 다른 내용으로 미리 push (현 상태로 push 후 본문 직접 변경)
    push_to_remote(local, remote_target, home=fake_home, now=now_fixed)
    # remote 본문을 다른 내용으로 손상 시뮬레이션
    (remote_target / "cc-inspect/health/2026-05-25.json").write_text("remote-different", encoding="utf-8")
    # remote manifest 도 새 sha256 로 수동 갱신 (push 가 detect 하도록)
    import hashlib
    rem_manifest = remote_target / REMOTE_MANIFEST_NAME
    data = json.loads(rem_manifest.read_text())
    for item in data["items"]:
        if item["relative_path"] == "cc-inspect/health/2026-05-25.json":
            item["sha256"] = hashlib.sha256(b"remote-different").hexdigest()
            item["size"] = len("remote-different")
    rem_manifest.write_text(json.dumps(data))

    # local 본문도 다른 내용으로 변경 → diff 발생
    _write_health(fake_home, "2026-05-25", "yet-another-local")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)

    # push without force
    result = push_to_remote(local, remote_target, home=fake_home, force=False, now=now_fixed)
    assert result.items_copied == 0
    assert result.items_skipped_conflict == 1
    # remote 본문이 안 바뀌었는지 (overwrite 없음)
    assert (remote_target / "cc-inspect/health/2026-05-25.json").read_text() == "remote-different"


def test_push_diff_overwrite_with_force(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """conflict 시 --force 면 local 본문으로 overwrite."""
    _write_health(fake_home, "2026-05-25", "v1-content")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    push_to_remote(local, remote_target, home=fake_home, now=now_fixed)

    # local 본문 변경
    _write_health(fake_home, "2026-05-25", "v2-overwrite")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)

    result = push_to_remote(local, remote_target, home=fake_home, force=True, now=now_fixed)
    assert result.items_copied == 1
    assert result.items_skipped_conflict == 0
    # remote 가 새 본문으로 overwrite
    assert (remote_target / "cc-inspect/health/2026-05-25.json").read_text() == "v2-overwrite"


def test_push_preserves_remote_only(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """push 는 remote-only items 를 삭제하지 않음."""
    _write_health(fake_home, "2026-05-25", "from-local")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)

    # remote 에만 있는 entry 를 수동으로 미리 push
    remote_target.mkdir(parents=True, exist_ok=True)
    (remote_target / "cc-inspect/health").mkdir(parents=True, exist_ok=True)
    (remote_target / "cc-inspect/health/2026-05-20.json").write_text("remote-only-data", encoding="utf-8")
    # remote manifest 에 entry 등록
    import hashlib
    pre_manifest = SyncTargetManifest(
        schema_version=1,
        machine_id="other-m",
        generated_at="2026-05-20T00:00:00Z",
        items=[
            SyncItem(
                kind=KIND_HEALTH_JSON,
                relative_path="cc-inspect/health/2026-05-20.json",
                size=len("remote-only-data"),
                sha256=hashlib.sha256(b"remote-only-data").hexdigest(),
                mtime="2026-05-20T00:00:00Z",
            )
        ],
    )
    (remote_target / REMOTE_MANIFEST_NAME).write_text(json.dumps(pre_manifest.to_dict()), encoding="utf-8")

    result = push_to_remote(local, remote_target, home=fake_home, now=now_fixed)
    assert result.items_copied == 1  # local 만 copy
    # remote-only 파일 보존
    assert (remote_target / "cc-inspect/health/2026-05-20.json").read_text() == "remote-only-data"
    # 새 manifest 가 local + remote-only 모두 포함
    m = load_remote_manifest(remote_target)
    assert m is not None
    paths = sorted(i.relative_path for i in m.items)
    assert "cc-inspect/health/2026-05-25.json" in paths
    assert "cc-inspect/health/2026-05-20.json" in paths


# ===== pull =====

def test_pull_remote_missing_raises(fake_home: Path, remote_target: Path) -> None:
    """remote manifest 없으면 SyncError."""
    with pytest.raises(SyncError, match="remote manifest 부재"):
        pull_to_local(remote_target, home=fake_home)


def test_pull_remote_only_copies_to_local(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """remote 의 health_json 을 local 에 mirror."""
    # remote 에 직접 file + manifest 작성
    remote_health = remote_target / "cc-inspect/health"
    remote_health.mkdir(parents=True)
    (remote_health / "2026-05-24.json").write_text("from-remote", encoding="utf-8")
    import hashlib
    manifest = SyncTargetManifest(
        schema_version=1,
        machine_id="other-m",
        generated_at="x",
        items=[
            SyncItem(
                kind=KIND_HEALTH_JSON,
                relative_path="cc-inspect/health/2026-05-24.json",
                size=len("from-remote"),
                sha256=hashlib.sha256(b"from-remote").hexdigest(),
                mtime="x",
            )
        ],
    )
    (remote_target / REMOTE_MANIFEST_NAME).write_text(json.dumps(manifest.to_dict()), encoding="utf-8")

    result = pull_to_local(remote_target, home=fake_home, now=now_fixed)
    assert result.operation == "pull"
    assert result.items_copied == 1
    assert result.items_failed == 0
    # local 에 mirror
    assert (fake_home / ".config/cc-inspect/health/2026-05-24.json").read_text() == "from-remote"


def test_pull_snapshot_meta_path_resolution(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """snapshot_meta 의 relative_path → local workspace/.anvyc/snapshots/<id>/meta.json 역매핑."""
    # remote 에 snapshot meta 작성
    remote_snap = remote_target / "anvyc/snapshots/myws-20260525T120000Z-deadbe"
    remote_snap.mkdir(parents=True)
    (remote_snap / "meta.json").write_text('{"snap":1}', encoding="utf-8")
    import hashlib
    manifest = SyncTargetManifest(
        schema_version=1,
        machine_id="other-m",
        generated_at="x",
        items=[
            SyncItem(
                kind=KIND_SNAPSHOT_META,
                relative_path="anvyc/snapshots/myws-20260525T120000Z-deadbe/meta.json",
                size=len('{"snap":1}'),
                sha256=hashlib.sha256(b'{"snap":1}').hexdigest(),
                mtime="x",
            )
        ],
    )
    (remote_target / REMOTE_MANIFEST_NAME).write_text(json.dumps(manifest.to_dict()), encoding="utf-8")

    result = pull_to_local(remote_target, home=fake_home, now=now_fixed)
    assert result.items_copied == 1
    # 역매핑된 local path 확인
    expected = fake_home / "dev/myws/.anvyc/snapshots/20260525T120000Z-deadbe/meta.json"
    assert expected.read_text() == '{"snap":1}'


def test_pull_account_bindings_path_resolution(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """account_bindings 의 relative_path → local `.config/anvyc/accounts/bindings.<host>.yaml` 역매핑."""
    remote_accounts = remote_target / "anvyc/accounts"
    remote_accounts.mkdir(parents=True)
    (remote_accounts / "bindings.other-host.yaml").write_text(
        "version: 1\naccounts: {}\n", encoding="utf-8"
    )
    import hashlib
    payload = b"version: 1\naccounts: {}\n"
    manifest = SyncTargetManifest(
        schema_version=1,
        machine_id="other-m",
        generated_at="x",
        items=[
            SyncItem(
                kind=KIND_ACCOUNT_BINDINGS,
                relative_path="anvyc/accounts/bindings.other-host.yaml",
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                mtime="x",
            )
        ],
    )
    (remote_target / REMOTE_MANIFEST_NAME).write_text(json.dumps(manifest.to_dict()), encoding="utf-8")

    result = pull_to_local(remote_target, home=fake_home, now=now_fixed)
    assert result.items_copied == 1
    assert result.items_failed == 0
    expected = fake_home / ".config/anvyc/accounts/bindings.other-host.yaml"
    assert expected.read_text() == "version: 1\naccounts: {}\n"


def test_push_account_bindings_copies_and_relative_path(
    fake_home: Path, remote_target: Path, now_fixed: datetime
) -> None:
    """account_bindings 가 push 시 실제로 copy 되고 relative_path 가 registry 규칙을 따르는가."""
    _write_account_bindings(fake_home, "my-host", "version: 1\naccounts: {}\n")
    local = scan_local_manifest(home=fake_home, machine_id="src-m", now=now_fixed)

    result = push_to_remote(local, remote_target, home=fake_home, now=now_fixed)
    assert result.items_copied == 1
    assert result.items_failed == 0
    copied = remote_target / "anvyc/accounts/bindings.my-host.yaml"
    assert copied.read_text() == "version: 1\naccounts: {}\n"

    m = load_remote_manifest(remote_target)
    assert m is not None
    assert m.items[0].kind == KIND_ACCOUNT_BINDINGS
    assert m.items[0].relative_path == "anvyc/accounts/bindings.my-host.yaml"


def test_pull_same_skipped(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """local 과 remote 가 동일 sha256 면 skip."""
    _write_health(fake_home, "2026-05-25", "match")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    # remote 동일 본문으로 push
    push_to_remote(local, remote_target, home=fake_home, now=now_fixed)

    # pull → same, copy 0
    result = pull_to_local(remote_target, home=fake_home, now=now_fixed)
    assert result.items_copied == 0
    assert result.items_skipped_same == 1


def test_pull_diff_skip_without_force(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """conflict 시 force 없으면 skip + local 본문 보존."""
    _write_health(fake_home, "2026-05-25", "local-keep-this")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    push_to_remote(local, remote_target, home=fake_home, now=now_fixed)

    # remote 본문 변경 + manifest sha 갱신
    import hashlib
    (remote_target / "cc-inspect/health/2026-05-25.json").write_text("remote-new", encoding="utf-8")
    data = json.loads((remote_target / REMOTE_MANIFEST_NAME).read_text())
    for item in data["items"]:
        if item["relative_path"] == "cc-inspect/health/2026-05-25.json":
            item["sha256"] = hashlib.sha256(b"remote-new").hexdigest()
            item["size"] = len("remote-new")
    (remote_target / REMOTE_MANIFEST_NAME).write_text(json.dumps(data))

    result = pull_to_local(remote_target, home=fake_home, force=False, now=now_fixed)
    assert result.items_copied == 0
    assert result.items_skipped_conflict == 1
    # local 본문 보존
    assert (fake_home / ".config/cc-inspect/health/2026-05-25.json").read_text() == "local-keep-this"


def test_pull_diff_overwrite_with_force(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """conflict 시 --force 면 local 본문 overwrite."""
    _write_health(fake_home, "2026-05-25", "old-local")
    local = scan_local_manifest(home=fake_home, machine_id="t", now=now_fixed)
    push_to_remote(local, remote_target, home=fake_home, now=now_fixed)

    # remote 본문 + manifest 갱신
    import hashlib
    (remote_target / "cc-inspect/health/2026-05-25.json").write_text("new-from-remote", encoding="utf-8")
    data = json.loads((remote_target / REMOTE_MANIFEST_NAME).read_text())
    for item in data["items"]:
        if item["relative_path"] == "cc-inspect/health/2026-05-25.json":
            item["sha256"] = hashlib.sha256(b"new-from-remote").hexdigest()
    (remote_target / REMOTE_MANIFEST_NAME).write_text(json.dumps(data))

    result = pull_to_local(remote_target, home=fake_home, force=True, now=now_fixed)
    assert result.items_copied == 1
    assert (fake_home / ".config/cc-inspect/health/2026-05-25.json").read_text() == "new-from-remote"


def test_pull_preserves_local_only(fake_home: Path, remote_target: Path, now_fixed: datetime) -> None:
    """pull 은 local-only items 를 삭제하지 않음."""
    # local 에만 있는 file
    _write_health(fake_home, "2026-05-21", "local-only")
    # remote 에는 다른 entry
    (remote_target / "cc-inspect/health").mkdir(parents=True, exist_ok=True)
    (remote_target / "cc-inspect/health/2026-05-22.json").write_text("remote-only", encoding="utf-8")
    import hashlib
    manifest = SyncTargetManifest(
        schema_version=1,
        machine_id="other-m",
        generated_at="x",
        items=[
            SyncItem(
                kind=KIND_HEALTH_JSON,
                relative_path="cc-inspect/health/2026-05-22.json",
                size=len("remote-only"),
                sha256=hashlib.sha256(b"remote-only").hexdigest(),
                mtime="x",
            )
        ],
    )
    (remote_target / REMOTE_MANIFEST_NAME).write_text(json.dumps(manifest.to_dict()), encoding="utf-8")

    pull_to_local(remote_target, home=fake_home, now=now_fixed)
    # local-only 파일이 그대로 있는지
    assert (fake_home / ".config/cc-inspect/health/2026-05-21.json").read_text() == "local-only"
    # remote-only 가 pull 됐는지
    assert (fake_home / ".config/cc-inspect/health/2026-05-22.json").read_text() == "remote-only"


def test_push_pull_roundtrip(fake_home: Path, remote_target: Path, now_fixed: datetime, tmp_path: Path) -> None:
    """push 후 다른 머신 (다른 home) 에서 pull 하면 동일 state 복원."""
    # 머신 A
    _write_health(fake_home, "2026-05-25", "axis-payload")
    _write_snapshot_meta(fake_home, "myws", "20260525T100000Z-cafe00", '{"label":"test"}')
    local_a = scan_local_manifest(home=fake_home, machine_id="machine-A", now=now_fixed)
    push_to_remote(local_a, remote_target, home=fake_home, now=now_fixed)

    # 머신 B (별 home)
    machine_b_home = tmp_path / "machine-B-home"
    machine_b_home.mkdir()
    pull_result = pull_to_local(remote_target, home=machine_b_home, now=now_fixed)
    assert pull_result.items_copied == 2

    # 머신 B 의 file 들이 동일 본문인지
    assert (machine_b_home / ".config/cc-inspect/health/2026-05-25.json").read_text() == "axis-payload"
    assert (machine_b_home / "dev/myws/.anvyc/snapshots/20260525T100000Z-cafe00/meta.json").read_text() == '{"label":"test"}'
