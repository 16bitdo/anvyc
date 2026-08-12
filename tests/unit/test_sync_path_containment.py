"""`_resolve_local_path_from_relative` 의 path traversal / 절대경로 치환 방어.

리뷰 Important-1: remote manifest 의 `relative_path` 는 신뢰할 수 없는 입력인데,
prefix 검사(`startswith`)만으로는 두 가지 우회를 못 막았다.

1. **이중 슬래시 절대경로화** — prefix 를 벗겨낸 뒤 남는 문자열이 `/` 로 시작하면
   그 자체로 절대경로가 되고, `PurePath.__truediv__` 는 절대경로 segment 를 만나면
   그 앞의 모든 segment 를 버린다: `root / "/etc/passwd"` == `Path("/etc/passwd")`.
   (참고: `target / relative_path` 처럼 **한 번의 `/` 호출로 전체 문자열을 합치는
   경우**는 중간의 `//` 가 그냥 하나의 구분자로 collapse 될 뿐 이 치환이 안 일어난다
   — `_resolve_local_path_from_relative` 가 prefix 를 슬라이싱한 "뒤" 별도로
   `/` 하는 지점에서만 발생한다.)
2. **`../` 상위 이동** — snapshot_meta 의 workspace 캡처 그룹(`(.+?)`)처럼 `/`·`..`
   를 배제하지 않는 정규식/슬라이싱을 거치면 그대로 상위 디렉터리로 빠져나간다.

3개 kind(snapshot_meta / health_json / account_bindings) 모두 같은 결함을 공유했다
(공유 함수를 통해 역매핑하기 때문). `_contained_local_path()` 가 반환 직전에
resolve 후 root 하위인지 확인해 막는다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from anvyc.core import sync as sync_module
from anvyc.core.sync import (
    KIND_ACCOUNT_BINDINGS,
    KIND_HEALTH_JSON,
    KIND_SNAPSHOT_META,
    REMOTE_MANIFEST_NAME,
    SyncConflictError,
    SyncItem,
    SyncTargetManifest,
    _contained_local_path,
    _resolve_local_path_from_relative,
    pull_to_local,
    resolve_conflict,
)


@pytest.fixture
def now_fixed() -> datetime:
    return datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    return h


def _traversal_to(root: Path, tmp_path: Path) -> str:
    """`root` 에서 `tmp_path` 까지 되돌아가는 `../` 문자열 (fixture 구조 변경에도 안전하도록 동적 계산)."""
    depth = len(root.relative_to(tmp_path).parts)
    return "/".join([".."] * depth)


def _absolute_swallow_relative(prefix: str, target: Path) -> str:
    """prefix 뒤에 절대경로를 그대로 이어붙여 이중 슬래시 우회 패턴을 만든다.

    prefix 가 "/" 로 끝나고 target 이 "/" 로 시작하므로, 이 문자열에서 prefix 를
    제거한 나머지(`relative[len(prefix):]`)는 `str(target)` 그 자체가 된다 —
    패치 전 코드라면 `root / that` 가 root 를 버리고 target 으로 치환됐다.
    """
    return f"{prefix}{target}"


# ===== _contained_local_path 자체 =====


def test_contained_local_path_normal_passes(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    candidate = root / "file.txt"
    assert _contained_local_path(root, candidate) == candidate


def test_contained_local_path_traversal_blocked(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    candidate = root / ".." / ".." / "escape.txt"
    assert _contained_local_path(root, candidate) is None


def test_contained_local_path_absolute_swallow_blocked(tmp_path: Path) -> None:
    """root / <절대경로> 는 root 를 버리고 절대경로 그 자체가 된다 (pathlib 관례) — 그걸 잡는다."""
    root = tmp_path / "root"
    root.mkdir()
    escape_target = tmp_path / "elsewhere" / "pwned.txt"
    candidate = root / str(escape_target)
    assert candidate == escape_target  # join 시점에 이미 root 소실 확인
    assert _contained_local_path(root, candidate) is None


def test_contained_local_path_symlink_escape_blocked(tmp_path: Path) -> None:
    """root 안의 symlink 가 root 밖을 가리켜도 resolve 후 판정하면 막힌다."""
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "link"
    link.symlink_to(outside)
    candidate = link / "pwned.txt"
    assert _contained_local_path(root, candidate) is None


# ===== _resolve_local_path_from_relative — kind 별 3종 (정상 / traversal / 절대경로 치환) =====

# --- account_bindings ---


def test_resolve_account_bindings_normal(fake_home: Path) -> None:
    result = _resolve_local_path_from_relative(fake_home, "anvyc/accounts/bindings.host-x.yaml", KIND_ACCOUNT_BINDINGS)
    assert result == fake_home / ".config" / "anvyc" / "accounts" / "bindings.host-x.yaml"


def test_resolve_account_bindings_traversal_blocked(fake_home: Path, tmp_path: Path) -> None:
    root = fake_home / ".config" / "anvyc" / "accounts"
    up = _traversal_to(root, tmp_path)
    relative = f"anvyc/accounts/{up}/escape/pwned.yaml"
    assert _resolve_local_path_from_relative(fake_home, relative, KIND_ACCOUNT_BINDINGS) is None


def test_resolve_account_bindings_absolute_swallow_blocked(fake_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "escape2" / "pwned2.yaml"
    relative = _absolute_swallow_relative("anvyc/accounts/", target)
    assert _resolve_local_path_from_relative(fake_home, relative, KIND_ACCOUNT_BINDINGS) is None


# --- health_json ---


def test_resolve_health_json_normal(fake_home: Path) -> None:
    result = _resolve_local_path_from_relative(fake_home, "cc-inspect/health/2026-05-25.json", KIND_HEALTH_JSON)
    assert result == fake_home / ".config" / "cc-inspect" / "health" / "2026-05-25.json"


def test_resolve_health_json_traversal_blocked(fake_home: Path, tmp_path: Path) -> None:
    root = fake_home / ".config" / "cc-inspect" / "health"
    up = _traversal_to(root, tmp_path)
    relative = f"cc-inspect/health/{up}/escape/pwned.json"
    assert _resolve_local_path_from_relative(fake_home, relative, KIND_HEALTH_JSON) is None


def test_resolve_health_json_absolute_swallow_blocked(fake_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "escape3" / "pwned3.json"
    relative = _absolute_swallow_relative("cc-inspect/health/", target)
    assert _resolve_local_path_from_relative(fake_home, relative, KIND_HEALTH_JSON) is None


# --- snapshot_meta ---


def test_resolve_snapshot_meta_normal(fake_home: Path) -> None:
    result = _resolve_local_path_from_relative(
        fake_home, "anvyc/snapshots/myws-20260525T100000Z-abcdef/meta.json", KIND_SNAPSHOT_META
    )
    assert result == fake_home / "dev" / "myws" / ".anvyc" / "snapshots" / "20260525T100000Z-abcdef" / "meta.json"


def test_resolve_snapshot_meta_traversal_blocked(fake_home: Path, tmp_path: Path) -> None:
    dev = fake_home / "dev"
    up = _traversal_to(dev, tmp_path)
    # workspace 캡처 그룹(.+?)은 "/"·".." 를 배제하지 않는다 — id suffix 는 유지해야 정규식이 매치.
    relative = f"anvyc/snapshots/{up}/escape-20260525T100000Z-abcdef/meta.json"
    assert _resolve_local_path_from_relative(fake_home, relative, KIND_SNAPSHOT_META) is None


def test_resolve_snapshot_meta_absolute_swallow_blocked(fake_home: Path, tmp_path: Path) -> None:
    # workspace 부분만 절대경로로 치환하고 "-<id>" suffix 는 유지 — regex 매치를 위해서.
    workspace_absolute = tmp_path / "escape4"
    relative = f"anvyc/snapshots/{workspace_absolute}-20260525T100000Z-abcdef/meta.json".replace(
        "anvyc/snapshots/", "anvyc/snapshots//", 1
    )
    assert _resolve_local_path_from_relative(fake_home, relative, KIND_SNAPSHOT_META) is None


# ===== end-to-end — 실제 호출부(pull_to_local / resolve_conflict)에서 파일이 안 새는가 =====


def test_pull_to_local_malicious_manifest_does_not_escape(fake_home: Path, tmp_path: Path, now_fixed: datetime) -> None:
    """remote manifest 에 절대경로 치환용 relative_path 를 심어도 root 밖에 파일이 안 생긴다.

    `src = target / entry.relative_path` (단일 join) 은 중간의 이중 슬래시를 그냥
    collapse 하므로 그 자체로는 안 새지만, 그렇게 collapse 된 위치에 실제로 remote
    payload 파일을 둬서 `src.is_file()` 을 통과시키고 — 진짜 위험 지점인 `dst`
    (local 역매핑, `_resolve_local_path_from_relative`)까지 도달하게 한다.
    """
    remote_target = tmp_path / "remote"
    escape_target = tmp_path / "escape5" / "pwned5.yaml"
    malicious_relative = _absolute_swallow_relative("anvyc/accounts/", escape_target)

    # src = target / malicious_relative 가 실제로 collapse 되는 위치에 payload 를 둔다
    # (하드코딩 대신 코드와 동일한 join 을 그대로 써서 위치를 계산 — 가정 불일치 방지).
    remote_payload = remote_target / malicious_relative
    remote_payload.parent.mkdir(parents=True)
    remote_payload.write_text("malicious-content", encoding="utf-8")

    manifest = SyncTargetManifest(
        schema_version=1,
        machine_id="attacker-m",
        generated_at="x",
        items=[
            SyncItem(
                kind=KIND_ACCOUNT_BINDINGS,
                relative_path=malicious_relative,
                size=len("malicious-content"),
                sha256=hashlib.sha256(b"malicious-content").hexdigest(),
                mtime="x",
            )
        ],
    )
    (remote_target / REMOTE_MANIFEST_NAME).write_text(json.dumps(manifest.to_dict()), encoding="utf-8")

    result = pull_to_local(remote_target, home=fake_home, now=now_fixed)

    assert result.items_copied == 0
    assert result.items_failed == 1
    assert malicious_relative in result.failed_paths
    assert not escape_target.exists()  # 핵심 — root 밖에 아무것도 안 생겼다
    assert not (fake_home / ".config" / "anvyc" / "accounts").exists()  # 정상 목적지에도 안 씀


def test_resolve_conflict_keep_remote_malicious_manifest_raises_not_writes(
    fake_home: Path, tmp_path: Path, now_fixed: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """resolve_conflict(keep="remote") 도 동일 함수를 쓴다 — containment 실패 시 SyncConflictError, 파일 안 씀.

    diff 상태(로컬·원격 양쪽에 동일 relative_path, 다른 sha256)에 실제로 도달하려면
    local scan 도 그 relative_path 를 만들어야 하는데, 정상 local scan
    (`_scan_account_bindings` 등)은 실제 로컬 파일명에서만 relative_path 를 생성하므로
    malicious 문자열을 스스로 만들 수 없다. 즉 이 경로는 "local 이 우연히 공격자와
    같은 이름을 골랐다"는 비현실적 전제 없이는 자연 발생하지 않는다.

    그래도 `resolve_conflict` 내부가 `_resolve_local_path_from_relative` 의 None
    을 정말로 SyncConflictError 로 승격하는지(조용히 무시하지 않는지)는 별도로
    검증할 가치가 있다 — scan_local_manifest 를 monkeypatch 해 diff 상태를
    인위적으로 만들어 그 방어선만 단독으로 확인한다(defense-in-depth 확인이지,
    이 경로가 실제로 이렇게 도달 가능하다는 주장이 아니다).
    """
    remote_target = tmp_path / "remote2"
    escape_target = tmp_path / "escape6" / "pwned6.yaml"
    malicious_relative = _absolute_swallow_relative("anvyc/accounts/", escape_target)

    fake_local_manifest = SyncTargetManifest(
        schema_version=1,
        machine_id="local-m",
        generated_at="x",
        items=[
            SyncItem(
                kind=KIND_ACCOUNT_BINDINGS,
                relative_path=malicious_relative,
                size=len("local-content"),
                sha256=hashlib.sha256(b"local-content").hexdigest(),
                mtime="x",
            )
        ],
    )
    monkeypatch.setattr(sync_module, "scan_local_manifest", lambda **kwargs: fake_local_manifest)

    remote_payload = remote_target / malicious_relative
    remote_payload.parent.mkdir(parents=True)
    remote_payload.write_text("remote-content", encoding="utf-8")

    manifest = SyncTargetManifest(
        schema_version=1,
        machine_id="attacker-m",
        generated_at="x",
        items=[
            SyncItem(
                kind=KIND_ACCOUNT_BINDINGS,
                relative_path=malicious_relative,
                size=len("remote-content"),
                sha256=hashlib.sha256(b"remote-content").hexdigest(),  # local 과 달라야 diff
                mtime="x",
            )
        ],
    )
    (remote_target / REMOTE_MANIFEST_NAME).write_text(json.dumps(manifest.to_dict()), encoding="utf-8")

    with pytest.raises(SyncConflictError, match="역매핑 실패"):
        resolve_conflict(remote_target, malicious_relative, keep="remote", home=fake_home, now=now_fixed)

    assert not escape_target.exists()  # 핵심 — SyncConflictError 이전에 파일이 안 써졌다
