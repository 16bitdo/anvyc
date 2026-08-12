"""Cross-machine state sync — CP-6 1/3 (+ rule 27 계정 바인딩 편입).

여러 머신 간 control plane mutable state (CP-3 health JSON + CP-4 snapshot
meta + 계정 바인딩) 동기화. 1/3 PR 은 schema v1 + `sync status` (read-only
drift detection) 만 — `sync push` / `pull` 은 2/3, conflict resolution 은
3/3. 계정 바인딩(`account_bindings`)은 그 이후 rule 27 대응으로 kind 목록에
추가됐다 — `core/account_manifest.py` 의 `~/.config/anvyc/accounts/
bindings.<hostname>.yaml` 이 source.

L12 (cross-axis schema 일관성) 의 sync 단위 안정성 입증 시점 — 모든 mutable
state 가 `schema_version: 1` 이라 sync target adapter 가 일반화 가능.

설계 원칙
- **단일 schema v1**: SyncTargetManifest (machine 별 항목 목록) — local /
  remote 양쪽 동일 형식. local 은 filesystem scan 으로 생성, remote 는
  파일 read.
- **kind 별 adapter**: `snapshot_meta` + `health_json` (1/3 MVP) +
  `account_bindings` (rule 27 대응 추가). creds expiry timestamp 는 후속
  polish (live computation 이라 파일 base 가 아님).
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
          "kind": "snapshot_meta" | "health_json" | "account_bindings",
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

import contextlib
import getpass
import hashlib
import json
import os
import re
import socket
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1
KIND_SNAPSHOT_META = "snapshot_meta"
KIND_HEALTH_JSON = "health_json"
KIND_ACCOUNT_BINDINGS = "account_bindings"
ALL_KINDS = (KIND_SNAPSHOT_META, KIND_HEALTH_JSON, KIND_ACCOUNT_BINDINGS)

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


def _scan_account_bindings(home: Path) -> list[SyncItem]:
    """scan `<home>/.config/anvyc/accounts/bindings.*.yaml` 으로 머신 계정 바인딩 발견.

    바인딩 파일은 public identifier(로그인명·커밋 이메일·alias·경로)만 담는 것이
    rule 27 §1 의 정책이다 — 이 스캔 함수는 그 정책을 강제하지 않는다. 파일이
    거기 있으면 크기·sha256·mtime 만 계산해 항목화할 뿐, 내용을 열어 검증하지는
    않는다 (내용 검증은 `anvyc scan-secrets` 의 책임).

    파일명이 `bindings.<hostname>.yaml` 로 머신마다 달라 여러 머신의 바인딩이
    같은 remote 경로에서 충돌하지 않는다 (rule 27 §2 전제).
    """
    root = home / ".config" / "anvyc" / "accounts"
    if not root.is_dir():
        return []
    out: list[SyncItem] = []
    for f in sorted(root.glob("bindings.*.yaml")):
        if not f.is_file():
            continue
        try:
            out.append(
                SyncItem(
                    kind=KIND_ACCOUNT_BINDINGS,
                    relative_path=f"anvyc/accounts/{f.name}",
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
    if KIND_ACCOUNT_BINDINGS in selected:
        items.extend(_scan_account_bindings(h))

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


# ===== Push / Pull (CP-6 2/3) =====
#
# read+write 단. 4-layer safety (CP-4 §35.7 미러):
#   1. dry-run plan (status entries 출력)
#   2. confirm prompt (CLI 단)
#   3. atomic per-file copy (tempfile + os.replace)
#   4. conflict 검출 — 기본 skip, --force 명시 시 overwrite

class SyncError(RuntimeError):
    """sync push/pull 실행 실패 (file copy / manifest write)."""


@dataclass(frozen=True)
class SyncOperationResult:
    """push 또는 pull 의 결과."""

    operation: str  # "push" | "pull"
    target: str
    items_copied: int
    items_skipped_conflict: int  # --force 없을 때 conflict skip
    items_skipped_same: int      # 이미 동일 — copy 불요
    items_failed: int
    failed_paths: list[str]
    manifest_written: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _atomic_copy(src: Path, dst: Path) -> None:
    """src → dst atomic copy. dst.parent 자동 mkdir.

    tempfile 을 dst.parent 에 만들어 동일 filesystem 보장 (os.replace 의
    atomicity 조건). 본문 copy 는 chunked read/write.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=dst.name + ".", dir=str(dst.parent))
    try:
        with os.fdopen(fd, "wb") as out_fh, src.open("rb") as in_fh:
            for chunk in iter(lambda: in_fh.read(65536), b""):
                out_fh.write(chunk)
        os.replace(tmp_path, dst)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _atomic_write_manifest(target: Path, manifest: SyncTargetManifest) -> None:
    """manifest JSON atomic write to <target>/REMOTE_MANIFEST_NAME."""
    path = target / REMOTE_MANIFEST_NAME
    target.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=REMOTE_MANIFEST_NAME + ".", dir=str(target))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(manifest.to_dict(), fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _resolve_local_path_from_relative(home: Path, relative: str, kind: str, dev_root: Path | None = None) -> Path | None:
    """relative_path 역매핑 — pull 시 사용.

    snapshot_meta: `anvyc/snapshots/<workspace>-<id>/meta.json`
      → `<home>/dev/<workspace>/.anvyc/snapshots/<id>/meta.json`
    health_json: `cc-inspect/health/<date>.json`
      → `<home>/.config/cc-inspect/health/<date>.json`
    account_bindings: `anvyc/accounts/bindings.<hostname>.yaml`
      → `<home>/.config/anvyc/accounts/bindings.<hostname>.yaml`

    역매핑 실패 / kind 알 수 없음 → None.
    """
    if kind == KIND_ACCOUNT_BINDINGS:
        prefix = "anvyc/accounts/"
        if not relative.startswith(prefix):
            return None
        filename = relative[len(prefix):]
        return home / ".config" / "anvyc" / "accounts" / filename

    if kind == KIND_SNAPSHOT_META:
        prefix = "anvyc/snapshots/"
        if not relative.startswith(prefix) or not relative.endswith("/meta.json"):
            return None
        # 중간 segment 가 "<workspace>-<id>" — 마지막 "-<id>" 분리.
        # id 형식: 20YYMMDDTHHMMSSZ-<6hex> = 22자 고정 (`Z-` 의 `-` 가 split 후 첫 토큰)
        # 안전한 분리: 우측에서 마지막 "-<6hex>" 직전 "T" 가 있는 substring 까지가 id.
        middle = relative[len(prefix):-len("/meta.json")]
        # id pattern: T...Z-<6hex>
        m = re.match(r"^(.+?)-(\d{8}T\d{6}Z-[0-9a-f]{6})$", middle)
        if not m:
            return None
        workspace, snap_id = m.group(1), m.group(2)
        dev = dev_root or (home / "dev")
        return dev / workspace / ".anvyc" / "snapshots" / snap_id / "meta.json"

    if kind == KIND_HEALTH_JSON:
        prefix = "cc-inspect/health/"
        if not relative.startswith(prefix):
            return None
        filename = relative[len(prefix):]
        return home / ".config" / "cc-inspect" / "health" / filename

    return None


def _resolve_source_path_for_push(home: Path, item: SyncItem, dev_root: Path | None = None) -> Path | None:
    """push 시 local source path 추출 — relative_path 역매핑 (pull 과 동일 로직)."""
    return _resolve_local_path_from_relative(home, item.relative_path, item.kind, dev_root=dev_root)


def push_to_remote(
    local: SyncTargetManifest,
    target: Path,
    *,
    home: Path | None = None,
    dev_root: Path | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> SyncOperationResult:
    """local items 를 remote target 에 mirror + manifest 갱신.

    - same: skip (already in sync)
    - local_only: copy
    - diff (remote 측 다른 sha256): force=False 면 skip + count;
      force=True 면 overwrite
    - remote_only: 무시 (push 는 local → remote 방향만)
    """
    h = home or Path.home()
    n = now or datetime.now(tz=UTC)
    remote = load_remote_manifest(target)
    report = compute_sync_status(local, remote, remote_target=target, now=n)

    copied = 0
    skipped_conflict = 0
    skipped_same = 0
    failed: list[str] = []

    for entry in report.diff_entries:
        if entry.status == STATUS_REMOTE_ONLY:
            continue  # push 방향 무관
        if entry.status == STATUS_SAME:
            skipped_same += 1
            continue
        if entry.status == STATUS_DIFF and not force:
            skipped_conflict += 1
            continue
        # local_only 또는 (diff + force) → copy
        if entry.local is None:
            failed.append(entry.relative_path)
            continue
        src = _resolve_source_path_for_push(h, entry.local, dev_root=dev_root)
        if src is None or not src.is_file():
            failed.append(entry.relative_path)
            continue
        dst = target / entry.relative_path
        try:
            _atomic_copy(src, dst)
            copied += 1
        except (OSError, RuntimeError):
            failed.append(entry.relative_path)

    # remote manifest 갱신 — copied + skipped_same + skipped_conflict 만 반영.
    # remote_only 도 보존 (push 는 삭제 안 함 — destructive 회피).
    new_items: list[SyncItem] = []
    # local item 들 (copy 됐거나 same)
    local_paths_committed = {
        entry.relative_path
        for entry in report.diff_entries
        if entry.status in (STATUS_SAME, STATUS_LOCAL_ONLY)
        or (entry.status == STATUS_DIFF and force and entry.local is not None)
    }
    failed_set = set(failed)
    for item in local.items:
        if item.relative_path in local_paths_committed and item.relative_path not in failed_set:
            new_items.append(item)
    # remote-only items 보존 (push 가 삭제 안 함)
    if remote:
        local_paths_set = {i.relative_path for i in local.items}
        for item in remote.items:
            if item.relative_path not in local_paths_set:
                new_items.append(item)

    new_manifest = SyncTargetManifest(
        schema_version=SCHEMA_VERSION,
        machine_id=local.machine_id,
        generated_at=_iso(n),
        items=new_items,
    )

    manifest_written = False
    try:
        _atomic_write_manifest(target, new_manifest)
        manifest_written = True
    except OSError as exc:
        raise SyncError(f"manifest write 실패: {exc}") from exc

    return SyncOperationResult(
        operation="push",
        target=str(target),
        items_copied=copied,
        items_skipped_conflict=skipped_conflict,
        items_skipped_same=skipped_same,
        items_failed=len(failed),
        failed_paths=failed,
        manifest_written=manifest_written,
    )


def pull_to_local(
    target: Path,
    *,
    home: Path | None = None,
    dev_root: Path | None = None,
    machine_id: str | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> SyncOperationResult:
    """remote items 를 local target 에 mirror.

    - same: skip
    - remote_only: copy to local target path
    - diff (local 측 다른 sha256): force=False 면 skip; force=True 면 overwrite
    - local_only: 무시 (pull 은 remote → local 방향만)
    """
    h = home or Path.home()
    n = now or datetime.now(tz=UTC)
    remote = load_remote_manifest(target)
    if remote is None:
        raise SyncError(
            f"remote manifest 부재 또는 손상: {target}/{REMOTE_MANIFEST_NAME}"
        )
    local = scan_local_manifest(home=h, dev_root=dev_root, machine_id=machine_id, now=n)
    report = compute_sync_status(local, remote, remote_target=target, now=n)

    copied = 0
    skipped_conflict = 0
    skipped_same = 0
    failed: list[str] = []

    for entry in report.diff_entries:
        if entry.status == STATUS_LOCAL_ONLY:
            continue  # pull 방향 무관
        if entry.status == STATUS_SAME:
            skipped_same += 1
            continue
        if entry.status == STATUS_DIFF and not force:
            skipped_conflict += 1
            continue
        # remote_only 또는 (diff + force) → copy
        if entry.remote is None:
            failed.append(entry.relative_path)
            continue
        src = target / entry.relative_path
        if not src.is_file():
            failed.append(entry.relative_path)
            continue
        dst = _resolve_local_path_from_relative(h, entry.relative_path, entry.remote.kind, dev_root=dev_root)
        if dst is None:
            failed.append(entry.relative_path)
            continue
        try:
            _atomic_copy(src, dst)
            copied += 1
        except (OSError, RuntimeError):
            failed.append(entry.relative_path)

    return SyncOperationResult(
        operation="pull",
        target=str(target),
        items_copied=copied,
        items_skipped_conflict=skipped_conflict,
        items_skipped_same=skipped_same,
        items_failed=len(failed),
        failed_paths=failed,
        manifest_written=False,  # pull 은 remote 만 read; local manifest 안 적음
    )


# ===== Conflict resolution (CP-6 3/3) =====
#
# 2/3 의 conflict 기본 skip + --force overwrite 만으로는 부족한 시나리오 —
# 사용자가 entry 별로 어느 쪽을 keep 할지 명시 결정. auto-merge / 3-way
# merge 는 본 axis 영구 제외 (rbr rule 27 명문화) — 사용자 prompt 우선.

KEEP_LOCAL = "local"
KEEP_REMOTE = "remote"
ALL_KEEP_CHOICES = (KEEP_LOCAL, KEEP_REMOTE)


class SyncConflictError(ValueError):
    """conflict resolve 입력/실행 오류."""


def list_conflicts(
    target: Path,
    *,
    home: Path | None = None,
    dev_root: Path | None = None,
    machine_id: str | None = None,
    now: datetime | None = None,
) -> list[SyncDiffEntry]:
    """현재 local vs remote 의 conflict (status=diff) entries 만 반환.

    Raises:
      SyncError: remote manifest 부재.
    """
    h = home or Path.home()
    n = now or datetime.now(tz=UTC)
    remote = load_remote_manifest(target)
    if remote is None:
        raise SyncError(
            f"remote manifest 부재 또는 손상: {target}/{REMOTE_MANIFEST_NAME}"
        )
    local = scan_local_manifest(home=h, dev_root=dev_root, machine_id=machine_id, now=n)
    report = compute_sync_status(local, remote, remote_target=target, now=n)
    return [e for e in report.diff_entries if e.status == STATUS_DIFF]


def resolve_conflict(
    target: Path,
    relative_path: str,
    *,
    keep: str,
    home: Path | None = None,
    dev_root: Path | None = None,
    machine_id: str | None = None,
    now: datetime | None = None,
) -> SyncOperationResult:
    """단일 entry 의 conflict 를 명시 해결.

    - keep="local" → local 본문을 remote 에 copy + manifest 갱신 (push-one)
    - keep="remote" → remote 본문을 local 에 copy (pull-one, local manifest
      는 없음 — anvyc 는 local manifest 저장 안 함, scan 으로 생성)

    Args:
      target: remote target path
      relative_path: 해결할 entry 의 relative_path
      keep: "local" | "remote"

    Raises:
      SyncConflictError: keep 값이 ALL_KEEP_CHOICES 외, 또는 해당 path
        가 conflict 가 아니거나 부재.
      SyncError: remote manifest / file 부재, copy 실패.
    """
    if keep not in ALL_KEEP_CHOICES:
        raise SyncConflictError(
            f"invalid --keep: {keep!r}. supported: {', '.join(ALL_KEEP_CHOICES)}"
        )

    h = home or Path.home()
    n = now or datetime.now(tz=UTC)
    remote = load_remote_manifest(target)
    if remote is None:
        raise SyncError(
            f"remote manifest 부재 또는 손상: {target}/{REMOTE_MANIFEST_NAME}"
        )
    local = scan_local_manifest(home=h, dev_root=dev_root, machine_id=machine_id, now=n)
    report = compute_sync_status(local, remote, remote_target=target, now=n)

    entry = next(
        (e for e in report.diff_entries if e.relative_path == relative_path and e.status == STATUS_DIFF),
        None,
    )
    if entry is None:
        raise SyncConflictError(
            f"no conflict at: {relative_path!r}. "
            f"`anvyc sync conflict list` 로 conflict 목록 확인."
        )

    if keep == KEEP_LOCAL:
        # local 본문을 remote 에 copy + manifest 갱신
        if entry.local is None:
            raise SyncConflictError(
                f"keep=local 인데 local entry 부재 (상태 불일치): {relative_path}"
            )
        src = _resolve_source_path_for_push(h, entry.local, dev_root=dev_root)
        if src is None or not src.is_file():
            raise SyncError(f"local source 파일 부재: {relative_path}")
        dst = target / relative_path
        _atomic_copy(src, dst)
        # manifest 의 해당 entry 만 local 의 SyncItem 으로 교체
        new_items = [
            entry.local if it.relative_path == relative_path else it
            for it in remote.items
        ]
        new_manifest = SyncTargetManifest(
            schema_version=SCHEMA_VERSION,
            machine_id=remote.machine_id,
            generated_at=_iso(n),
            items=new_items,
        )
        _atomic_write_manifest(target, new_manifest)
        return SyncOperationResult(
            operation="conflict-keep-local",
            target=str(target),
            items_copied=1,
            items_skipped_conflict=0,
            items_skipped_same=0,
            items_failed=0,
            failed_paths=[],
            manifest_written=True,
        )

    # keep == "remote"
    if entry.remote is None:
        raise SyncConflictError(
            f"keep=remote 인데 remote entry 부재 (상태 불일치): {relative_path}"
        )
    src = target / relative_path
    if not src.is_file():
        raise SyncError(f"remote source 파일 부재: {src}")
    local_dst = _resolve_local_path_from_relative(h, relative_path, entry.remote.kind, dev_root=dev_root)
    if local_dst is None:
        raise SyncConflictError(
            f"relative_path 역매핑 실패: {relative_path!r} (kind={entry.remote.kind})"
        )
    _atomic_copy(src, local_dst)
    return SyncOperationResult(
        operation="conflict-keep-remote",
        target=str(target),
        items_copied=1,
        items_skipped_conflict=0,
        items_skipped_same=0,
        items_failed=0,
        failed_paths=[],
        manifest_written=False,
    )
