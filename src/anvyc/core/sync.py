"""Cross-machine state sync — CP-6 1/3.

여러 머신 간 control plane mutable state (CP-3 health JSON + CP-4 snapshot
meta) 동기화. 1/3 PR 은 schema v1 + `sync status` (read-only drift detection)
만 — `sync push` / `pull` 은 2/3, conflict resolution 은 3/3.

L12 (cross-axis schema 일관성) 의 sync 단위 안정성 입증 시점 — 모든 mutable
state 가 `schema_version: 1` 이라 sync target adapter 가 일반화 가능.

설계 원칙
- **단일 schema v1**: SyncTargetManifest (machine 별 항목 목록) — local /
  remote 양쪽 동일 형식. local 은 filesystem scan 으로 생성, remote 는
  파일 read.
- **kind 별 adapter** (1/3 MVP): `snapshot_meta` + `health_json` 만 지원.
  creds expiry timestamp 는 후속 polish (live computation 이라 파일 base 가
  아님).
- **Remote target = filesystem path** (1/3): local mount / git clone /
  sync 폴더 (Dropbox / iCloud). HTTPS / S3 backend 는 후속 polish.
- **machine_id**: 사용자 명시 (`anvyc.yaml` 의 `sync.machine_id`) > env
  (`ANVYC_MACHINE_ID`) > default `<user>@<hostname>`.

Schema v1:

    {
      "schema_version": 1,
      "machine_id": "edward@mbp-edward",
      "generated_at": "2026-05-25T10:00:00Z",
      "items": [
        {
          "kind": "snapshot_meta" | "health_json",
          "relative_path": "anvyc/snapshots/<workspace>-<id>/meta.json",
          "size": 512,
          "sha256": "abc123...",
          "mtime": "2026-05-25T09:30:00Z"
        },
        ...
      ]
    }
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import socket
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1
KIND_SNAPSHOT_META = "snapshot_meta"
KIND_HEALTH_JSON = "health_json"
ALL_KINDS = (KIND_SNAPSHOT_META, KIND_HEALTH_JSON)

# remote manifest filename
REMOTE_MANIFEST_NAME = "anvyc-sync-manifest.json"

# diff status
STATUS_SAME = "same"
STATUS_LOCAL_ONLY = "local_only"
STATUS_REMOTE_ONLY = "remote_only"
STATUS_DIFF = "diff"


@dataclass(frozen=True)
class SyncItem:
    """sync 대상 단일 file entry."""

    kind: str
    relative_path: str
    size: int
    sha256: str
    mtime: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SyncTargetManifest:
    """sync target manifest schema v1."""

    schema_version: int
    machine_id: str
    generated_at: str
    items: list[SyncItem]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "machine_id": self.machine_id,
            "generated_at": self.generated_at,
            "items": [i.to_dict() for i in self.items],
        }


@dataclass(frozen=True)
class SyncDiffEntry:
    """diff 한 entry 의 상태."""

    relative_path: str
    status: str  # same | local_only | remote_only | diff
    local: SyncItem | None
    remote: SyncItem | None

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "status": self.status,
            "local": self.local.to_dict() if self.local else None,
            "remote": self.remote.to_dict() if self.remote else None,
        }


@dataclass(frozen=True)
class SyncStatusReport:
    """`sync status` 의 종합 결과."""

    schema_version: int
    machine_id: str
    remote_target: str | None
    checked_at: str
    summary: dict[str, int]   # {same, local_only, remote_only, diff}
    diff_entries: list[SyncDiffEntry]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "machine_id": self.machine_id,
            "remote_target": self.remote_target,
            "checked_at": self.checked_at,
            "summary": self.summary,
            "diff_entries": [e.to_dict() for e in self.diff_entries],
        }


def resolve_machine_id(explicit: str | None = None) -> str:
    """우선순위: explicit > env ANVYC_MACHINE_ID > <user>@<hostname>."""
    if explicit:
        return explicit
    env = os.environ.get("ANVYC_MACHINE_ID")
    if env:
        return env
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    try:
        host = socket.gethostname()
    except Exception:
        host = "unknown"
    return f"{user}@{host}"


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mtime_iso(path: Path) -> str:
    return _iso(datetime.fromtimestamp(path.stat().st_mtime, tz=UTC))


def _scan_snapshot_meta(home: Path, dev_root: Path | None = None) -> list[SyncItem]:
    """scan `<dev_root>/*/.anvyc/snapshots/<id>/meta.json` 으로 CP-4 snapshot meta 발견.

    `dev_root` 미지정 시 `<home>/dev` 사용 (사용자 컨벤션). 디렉터리 부재
    → 빈 list.
    """
    root = dev_root or (home / "dev")
    if not root.is_dir():
        return []
    out: list[SyncItem] = []
    for workspace_dir in sorted(root.iterdir()):
        if not workspace_dir.is_dir():
            continue
        snapshots = workspace_dir / ".anvyc" / "snapshots"
        if not snapshots.is_dir():
            continue
        for snap_dir in sorted(snapshots.iterdir()):
            meta = snap_dir / "meta.json"
            if not meta.is_file():
                continue
            relative = f"anvyc/snapshots/{workspace_dir.name}-{snap_dir.name}/meta.json"
            try:
                out.append(
                    SyncItem(
                        kind=KIND_SNAPSHOT_META,
                        relative_path=relative,
                        size=meta.stat().st_size,
                        sha256=_sha256_of_file(meta),
                        mtime=_mtime_iso(meta),
                    )
                )
            except OSError:
                continue
    return out


def _scan_health_json(home: Path) -> list[SyncItem]:
    """scan `<home>/.config/cc-inspect/health/*.json` 으로 CP-3 health JSON 발견."""
    root = home / ".config" / "cc-inspect" / "health"
    if not root.is_dir():
        return []
    out: list[SyncItem] = []
    for f in sorted(root.glob("*.json")):
        if not f.is_file():
            continue
        try:
            out.append(
                SyncItem(
                    kind=KIND_HEALTH_JSON,
                    relative_path=f"cc-inspect/health/{f.name}",
                    size=f.stat().st_size,
                    sha256=_sha256_of_file(f),
                    mtime=_mtime_iso(f),
                )
            )
        except OSError:
            continue
    return out


def scan_local_manifest(
    *,
    home: Path | None = None,
    dev_root: Path | None = None,
    machine_id: str | None = None,
    kinds: list[str] | None = None,
    now: datetime | None = None,
) -> SyncTargetManifest:
    """local filesystem scan → schema v1 manifest 반환.

    Args:
      home: 사용자 home (기본 Path.home()).
      dev_root: workspace 루트 (기본 `<home>/dev`).
      machine_id: explicit override (없으면 `resolve_machine_id()`).
      kinds: 포함할 kind list (기본 ALL_KINDS).
      now: generated_at 기준 (기본 datetime.now(UTC)).
    """
    h = home or Path.home()
    n = now or datetime.now(tz=UTC)
    selected = set(kinds) if kinds else set(ALL_KINDS)

    items: list[SyncItem] = []
    if KIND_SNAPSHOT_META in selected:
        items.extend(_scan_snapshot_meta(h, dev_root=dev_root))
    if KIND_HEALTH_JSON in selected:
        items.extend(_scan_health_json(h))

    return SyncTargetManifest(
        schema_version=SCHEMA_VERSION,
        machine_id=resolve_machine_id(machine_id),
        generated_at=_iso(n),
        items=items,
    )


def load_remote_manifest(remote_target: Path) -> SyncTargetManifest | None:
    """remote target 의 manifest 파일 read. 부재 / 손상 시 None.

    Remote layout: `<remote_target>/<machine_id>/anvyc-sync-manifest.json` +
    payload files. 1/3 의 sync status 는 단일 remote machine_id 기준 — 다중
    machine 비교는 2/3 polish.

    실제로는 caller (cli) 가 remote_target 내 모든 machine_id 디렉터리 순회
    + manifest 합치는 방식도 가능. 1/3 MVP 는 단순화 — caller 가 한 머신
    경로 명시.
    """
    manifest_path = remote_target / REMOTE_MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    try:
        with manifest_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return None
    try:
        items = [
            SyncItem(
                kind=str(d["kind"]),
                relative_path=str(d["relative_path"]),
                size=int(d.get("size", 0)),
                sha256=str(d.get("sha256", "")),
                mtime=str(d.get("mtime", "")),
            )
            for d in (data.get("items") or [])
            if isinstance(d, dict) and "kind" in d and "relative_path" in d
        ]
        return SyncTargetManifest(
            schema_version=SCHEMA_VERSION,
            machine_id=str(data.get("machine_id", "")),
            generated_at=str(data.get("generated_at", "")),
            items=items,
        )
    except (KeyError, ValueError, TypeError):
        return None


def compute_sync_status(
    local: SyncTargetManifest,
    remote: SyncTargetManifest | None,
    *,
    remote_target: Path | None = None,
    now: datetime | None = None,
) -> SyncStatusReport:
    """local vs remote manifest diff → SyncStatusReport.

    Remote=None (manifest 부재) 면 모든 local items 가 `local_only`.
    """
    n = now or datetime.now(tz=UTC)
    remote_items: dict[str, SyncItem] = (
        {i.relative_path: i for i in remote.items} if remote else {}
    )
    local_items: dict[str, SyncItem] = {i.relative_path: i for i in local.items}

    diff_entries: list[SyncDiffEntry] = []
    counts = {STATUS_SAME: 0, STATUS_LOCAL_ONLY: 0, STATUS_REMOTE_ONLY: 0, STATUS_DIFF: 0}

    all_paths = sorted(set(local_items) | set(remote_items))
    for path in all_paths:
        loc = local_items.get(path)
        rem = remote_items.get(path)
        if loc and rem:
            status = STATUS_SAME if loc.sha256 == rem.sha256 else STATUS_DIFF
        elif loc and not rem:
            status = STATUS_LOCAL_ONLY
        elif rem and not loc:
            status = STATUS_REMOTE_ONLY
        else:
            continue  # 둘 다 None — 불가능
        counts[status] += 1
        diff_entries.append(
            SyncDiffEntry(
                relative_path=path,
                status=status,
                local=loc,
                remote=rem,
            )
        )

    return SyncStatusReport(
        schema_version=SCHEMA_VERSION,
        machine_id=local.machine_id,
        remote_target=str(remote_target) if remote_target else None,
        checked_at=_iso(n),
        summary=counts,
        diff_entries=diff_entries,
    )
