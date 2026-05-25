"""Workspace snapshot (작업 회복) — CP-4 (anvyc#29) 의 핵심.

autopilot 의 실수 (브랜치 30 파일 수정 등) 를 명시적 snapshot 으로 되돌리기
위한 capture / query / restore. CP-4 axis 의 3 PR 시퀀스 (1/3 create →
2/3 list/diff → 3/3 restore) 가 모두 본 모듈에 통합.

설계 원칙
- **Non-disruptive capture**: `git stash create` 로 working tree 를 건드리지
  않고 commit object 만 생성. `git update-ref refs/anvyc-snapshots/<id>` 로
  GC 방지 anchor — 사용자 `git stash drop` 같은 명령에 영향 받지 않음.
- **Storage 위치**: `.anvyc/snapshots/<id>/meta.json` (workspace-local).
  같은 `.anvyc/` 영역 (backup/) 와 분리된 sub-tree.
- **Schema v1**: 후속 PR (list/diff/restore) 의 입력 contract — 본 1/3 PR
  머지 시 schema 안정화. v1 cut-over 학습 L7 적용.

Meta schema v1:

    {
      "schema_version": 1,
      "id": "20260524T013000Z-a1b2c3",
      "label": "before-refactor",                  # 선택 (CLI --label)
      "claude_session_id": "abc-def-...",          # 선택 (env or CLI)
      "git_branch": "feat/foo",                    # 현재 branch (detached 시 sha)
      "git_stash_ref": "refs/anvyc-snapshots/...", # anchor ref (없으면 null)
      "git_stash_sha": "<commit-sha>",             # stash commit (없으면 null)
      "created_at": "2026-05-24T01:30:00Z",        # ISO8601 UTC
      "uncommitted_count": 5,                      # tracked + untracked 파일 수
      "working_clean": false                       # uncommitted_count == 0
    }
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1
SNAPSHOTS_SUBDIR = "snapshots"
STASH_REF_PREFIX = "refs/anvyc-snapshots"


@dataclass(frozen=True)
class SnapshotMeta:
    """Snapshot meta — v1 schema 의 in-memory 표현."""

    schema_version: int
    id: str
    label: str | None
    claude_session_id: str | None
    git_branch: str | None
    git_stash_ref: str | None
    git_stash_sha: str | None
    created_at: str
    uncommitted_count: int
    working_clean: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _new_id() -> str:
    """Sortable + unique snapshot id."""
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    rand = secrets.token_hex(3)  # 6 hex chars
    return f"{ts}-{rand}"


def _run_git(repo: Path, *args: str) -> tuple[int, str, str]:
    """git 실행 — (returncode, stdout, stderr) 반환. 예외 raise 안 함."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _detect_branch(repo: Path) -> str | None:
    """현재 branch (detached HEAD 시 sha)."""
    rc, out, _ = _run_git(repo, "symbolic-ref", "--short", "HEAD")
    if rc == 0 and out:
        return out
    rc, out, _ = _run_git(repo, "rev-parse", "HEAD")
    return out if rc == 0 and out else None


def _detect_uncommitted_count(repo: Path) -> int:
    """tracked 변경 + untracked 파일 수 (git status --porcelain 라인 수)."""
    rc, out, _ = _run_git(repo, "status", "--porcelain")
    if rc != 0:
        return 0
    return sum(1 for line in out.splitlines() if line.strip())


def _detect_session_id(explicit: str | None) -> str | None:
    """Claude session id — CLI 명시값 우선, 그 외 환경변수 fallback.

    Claude Code 환경에서 session id 가 env 로 노출되는지 확정적이지 않아
    아래 후보 명을 순차 시도. 미발견 시 null.
    """
    if explicit:
        return explicit
    for key in ("CLAUDE_SESSION_ID", "CLAUDECODE_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        val = os.environ.get(key)
        if val:
            return val
    return None


def _capture_stash(repo: Path, snapshot_id: str) -> tuple[str | None, str | None]:
    """현재 워킹트리 (tracked + **untracked**) 를 stash 로 capture + anchor.

    구현 — push + 즉시 pop 방식:
      1. `git stash push -u --quiet -m "anvyc-snapshot-<id>"` — untracked 포함
         stash 생성 (working tree 가 clean 으로 변함)
      2. `git rev-parse stash@{0}` — top stash 의 commit SHA capture
      3. `git update-ref refs/anvyc-snapshots/<id> <sha>` — anchor (GC 방지)
      4. `git stash pop --quiet --index` — working tree 복원 (anchor 가 이미
         있으므로 stack 에서 제거되어도 SHA 보존)

    `git stash create -u` 가 untracked 를 실제로 포함하지 않는 git plumbing
    제한 회피 — `stash push -u` 의 full stash entry (tracked + index +
    untracked 3-parent) 형태가 `apply` 시 untracked 도 복원.

    working tree 가 완전 clean (no tracked changes + no untracked) 이면
    `push` 가 non-zero 로 실패 → (None, None) 반환 = clean marker.

    Returns:
      (stash_ref, stash_sha) — clean tree 시 (None, None). anchor 실패 시
      (None, sha) — caller 가 보존 결정.
    """
    msg = f"anvyc-snapshot-{snapshot_id}"
    rc, _, _ = _run_git(repo, "stash", "push", "-u", "--quiet", "-m", msg)
    if rc != 0:
        # 변경 없음 — clean marker
        return None, None

    # top stash 의 SHA 즉시 capture
    rc_rev, sha, _ = _run_git(repo, "rev-parse", "stash@{0}")
    if rc_rev != 0 or not sha:
        # 비정상 — 복원 시도 후 실패 반환
        _run_git(repo, "stash", "pop", "--quiet", "--index")
        return None, None

    # anchor 먼저 (pop 이 실패해도 SHA 가 ref 로 보존되도록)
    ref = f"{STASH_REF_PREFIX}/{snapshot_id}"
    rc_anchor, _, _ = _run_git(repo, "update-ref", ref, sha)

    # working tree 복원
    rc_pop, _, pop_err = _run_git(repo, "stash", "pop", "--quiet", "--index")
    if rc_pop != 0:
        # pop 실패 — stash entry 는 stack 에 남아 있어 사용자가 수동 복구 가능.
        # (push -u 의 message "anvyc-snapshot-<id>" 로 식별 가능)
        # anchor 는 시도됐으므로 ref 가 있으면 반환.
        if rc_anchor == 0:
            return ref, sha
        return None, sha

    if rc_anchor != 0:
        return None, sha
    return ref, sha


def _atomic_write_json(path: Path, data: dict[str, object]) -> None:
    """tempfile + os.replace 로 atomic write (CP-3 health-append 패턴 미러)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)


def create_snapshot(
    repo: Path,
    anvyc_dir: Path,
    *,
    label: str | None = None,
    session_id: str | None = None,
) -> SnapshotMeta:
    """현재 workspace 의 snapshot 1건 생성.

    Args:
      repo:        git repo 루트 (working tree).
      anvyc_dir:   `.anvyc/` 디렉터리 (snapshots/ subdir 가 그 안에 생성됨).
      label:       사람 가독 label (선택 — `--label "<…>"` CLI 옵션).
      session_id:  Claude session id 명시 override (선택). 미지정 시 env 추출.

    Returns:
      SnapshotMeta — in-memory 표현. meta.json 은 .anvyc/snapshots/<id>/meta.json
      에 atomic write 완료된 상태.

    Raises:
      ValueError: `repo` 가 git working tree 가 아님.

    Note:
      working tree 가 clean (변경 없음) 이어도 snapshot 은 생성됨 —
      `git_stash_sha=null`, `working_clean=true` 로 표시. 시점 marker 로
      유용 (예: pre-autopilot 상태 anchor).
    """
    if not (repo / ".git").exists() and not _run_git(repo, "rev-parse", "--git-dir")[0] == 0:
        raise ValueError(f"not a git working tree: {repo}")

    snapshot_id = _new_id()
    branch = _detect_branch(repo)
    uncommitted = _detect_uncommitted_count(repo)
    stash_ref, stash_sha = _capture_stash(repo, snapshot_id)
    resolved_session = _detect_session_id(session_id)
    created_at = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    meta = SnapshotMeta(
        schema_version=SCHEMA_VERSION,
        id=snapshot_id,
        label=label,
        claude_session_id=resolved_session,
        git_branch=branch,
        git_stash_ref=stash_ref,
        git_stash_sha=stash_sha,
        created_at=created_at,
        uncommitted_count=uncommitted,
        working_clean=(uncommitted == 0),
    )

    snap_dir = anvyc_dir / SNAPSHOTS_SUBDIR / snapshot_id
    _atomic_write_json(snap_dir / "meta.json", meta.to_dict())

    return meta


def _load_meta(meta_path: Path) -> SnapshotMeta | None:
    """meta.json 1건 로드 — schema_version 미스매치 / 손상 시 None."""
    try:
        with meta_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return None
    try:
        return SnapshotMeta(
            schema_version=data["schema_version"],
            id=data["id"],
            label=data.get("label"),
            claude_session_id=data.get("claude_session_id"),
            git_branch=data.get("git_branch"),
            git_stash_ref=data.get("git_stash_ref"),
            git_stash_sha=data.get("git_stash_sha"),
            created_at=data["created_at"],
            uncommitted_count=int(data.get("uncommitted_count", 0)),
            working_clean=bool(data.get("working_clean", False)),
        )
    except (KeyError, ValueError, TypeError):
        return None


def list_snapshots(anvyc_dir: Path) -> list[SnapshotMeta]:
    """`.anvyc/snapshots/*/meta.json` 인덱스를 `created_at` 내림차순으로 반환.

    - 디렉터리 부재 → 빈 list.
    - meta.json 부재 / 손상 / version 미스매치 항목은 silently skip
      (corrupt 처리는 1/3 의 health-append 패턴과 일관).
    """
    root = anvyc_dir / SNAPSHOTS_SUBDIR
    if not root.is_dir():
        return []
    metas: list[SnapshotMeta] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        m = _load_meta(entry / "meta.json")
        if m is not None:
            metas.append(m)
    metas.sort(key=lambda m: m.created_at, reverse=True)
    return metas


def get_snapshot(anvyc_dir: Path, snapshot_id: str) -> SnapshotMeta | None:
    """단일 snapshot meta 조회. 부재 / 손상 시 None."""
    return _load_meta(anvyc_dir / SNAPSHOTS_SUBDIR / snapshot_id / "meta.json")


class SnapshotNotFoundError(ValueError):
    """주어진 snapshot id 가 anvyc_dir 에 없거나 손상."""


class SnapshotDiffError(RuntimeError):
    """git diff 실행 실패 (ref unreachable 등)."""


class SnapshotRestoreError(RuntimeError):
    """snapshot restore 실행 실패 (conflict / ref unreachable / git apply 실패 등)."""


@dataclass(frozen=True)
class RestorePlan:
    """`restore --dry-run` 의 출력 — 실제 수행 직전의 변경 plan."""

    target_id: str
    target_label: str | None
    target_branch: str | None
    target_stash_sha: str | None
    target_working_clean: bool
    current_branch: str | None
    current_uncommitted_count: int
    will_create_pre_restore_snapshot: bool
    git_apply_command: list[str]  # 실제 실행될 git argv (디버깅용)
    warnings: list[str]  # 사용자 주의 사항


@dataclass(frozen=True)
class RestoreResult:
    """`restore` 실 수행 결과."""

    target_id: str
    pre_restore_snapshot_id: str | None  # auto-create 된 safety snapshot
    applied: bool                          # git stash apply 가 정말 수행됐는지
    git_apply_stdout: str
    git_apply_stderr: str


def diff_snapshot(
    repo: Path,
    anvyc_dir: Path,
    snapshot_id: str,
    *,
    against: str | None = None,
) -> str:
    """snapshot 의 working tree state 와 비교 대상 간 unified diff 반환.

    - `against=None`: snapshot 시점의 git stash sha ↔ **현재 working tree** 비교.
      snapshot 의 `working_clean=true` (stash_sha=null) 인 경우 안내 메시지 반환.
    - `against=<other-id>`: 두 snapshot 의 stash sha 간 비교. 한쪽이라도
      `working_clean=true` 면 안내 메시지 반환.

    Raises:
      SnapshotNotFoundError: snapshot_id 또는 against 가 부재.
      SnapshotDiffError: git diff 실행이 실패 (ref unreachable / repo 문제).

    Note:
      git stash sha 는 워킹트리 변경분 + index 변경분의 합쳐진 tree commit.
      `git diff <sha>` 는 그 tree 와 현재 working tree 의 차이 (양방향 모두 보임).
    """
    base = get_snapshot(anvyc_dir, snapshot_id)
    if base is None:
        raise SnapshotNotFoundError(f"snapshot not found: {snapshot_id}")

    if against is None:
        if base.git_stash_sha is None:
            return (
                f"# snapshot {base.id} 은 working_clean=true (capture 시점 깨끗) — "
                "비교할 stash sha 없음. 시점 marker 로만 의미."
            )
        rc, out, err = _run_git(repo, "diff", base.git_stash_sha)
        if rc != 0:
            raise SnapshotDiffError(
                f"git diff {base.git_stash_sha} 실패: {err or 'unknown error'}"
            )
        return out

    other = get_snapshot(anvyc_dir, against)
    if other is None:
        raise SnapshotNotFoundError(f"snapshot not found: {against}")
    if base.git_stash_sha is None or other.git_stash_sha is None:
        return (
            f"# 한쪽 snapshot 이 working_clean=true (stash sha 없음): "
            f"{base.id}.stash={base.git_stash_sha} vs {other.id}.stash={other.git_stash_sha}"
        )
    rc, out, err = _run_git(repo, "diff", base.git_stash_sha, other.git_stash_sha)
    if rc != 0:
        raise SnapshotDiffError(
            f"git diff {base.git_stash_sha} {other.git_stash_sha} 실패: "
            f"{err or 'unknown error'}"
        )
    return out


def plan_restore(
    repo: Path,
    anvyc_dir: Path,
    snapshot_id: str,
) -> RestorePlan:
    """restore 직전의 plan 작성 (dry-run 출력 및 실제 수행 모두 사용).

    Raises:
      SnapshotNotFoundError: snapshot_id 가 부재.
    """
    target = get_snapshot(anvyc_dir, snapshot_id)
    if target is None:
        raise SnapshotNotFoundError(f"snapshot not found: {snapshot_id}")

    cur_branch = _detect_branch(repo)
    cur_uncommitted = _detect_uncommitted_count(repo)

    warnings: list[str] = []
    if target.working_clean:
        warnings.append(
            "target snapshot 이 working_clean=true — 적용할 stash 가 없음. "
            "restore 는 no-op (시점 marker 의미만)."
        )
    if cur_uncommitted > 0:
        warnings.append(
            f"현재 working tree 에 {cur_uncommitted} 개 변경 — "
            "pre-restore snapshot 자동 생성으로 보호되지만 conflict 가능."
        )
    if target.git_branch and cur_branch and target.git_branch != cur_branch:
        warnings.append(
            f"branch 불일치: 현재 '{cur_branch}' vs target '{target.git_branch}' — "
            "restore 는 branch 전환 안 함 (stash apply 만). 필요 시 사용자가 명시 checkout."
        )

    if target.git_stash_sha is None:
        # clean marker — git apply 불요
        cmd: list[str] = []
    else:
        cmd = ["git", "-C", str(repo), "stash", "apply", target.git_stash_sha]

    return RestorePlan(
        target_id=target.id,
        target_label=target.label,
        target_branch=target.git_branch,
        target_stash_sha=target.git_stash_sha,
        target_working_clean=target.working_clean,
        current_branch=cur_branch,
        current_uncommitted_count=cur_uncommitted,
        will_create_pre_restore_snapshot=(not target.working_clean),
        git_apply_command=cmd,
        warnings=warnings,
    )


def restore_snapshot(
    repo: Path,
    anvyc_dir: Path,
    snapshot_id: str,
) -> RestoreResult:
    """snapshot 시점의 working tree 변경분을 현재 위에 apply.

    안전 절차:
      1. target snapshot 조회 (없으면 raise)
      2. target 이 clean marker (stash sha=null) 면 no-op + 안내
      3. **auto pre-restore snapshot** 생성 — 현 working tree 를
         label=`pre-restore-<target-id>` 로 capture (실패 시 raise — 보호 없이
         restore 진행 금지)
      4. `git stash apply <target-stash-sha>` 실행
      5. git 의 exit code 가 0 이 아니면 SnapshotRestoreError (conflict 등) —
         이미 생성된 pre-restore snapshot id 는 err message 에 안내

    Raises:
      SnapshotNotFoundError: snapshot_id 부재.
      SnapshotRestoreError: pre-restore 실패 또는 git stash apply 실패.

    Note:
      본 함수는 CLI 의 --force / --dry-run 분기를 신경 쓰지 않음 — caller 가
      이미 결정한 후 호출. CLI 가 dry-run plan_restore() 또는 force
      restore_snapshot() 두 분기 명확화.
    """
    target = get_snapshot(anvyc_dir, snapshot_id)
    if target is None:
        raise SnapshotNotFoundError(f"snapshot not found: {snapshot_id}")

    if target.git_stash_sha is None:
        # clean marker — apply 할 stash 없음. no-op.
        return RestoreResult(
            target_id=target.id,
            pre_restore_snapshot_id=None,
            applied=False,
            git_apply_stdout="",
            git_apply_stderr="",
        )

    # auto pre-restore snapshot — 현 상태 보호 (실패 시 restore 진행 금지)
    try:
        pre = create_snapshot(
            repo,
            anvyc_dir,
            label=f"pre-restore-{target.id}",
            session_id=None,
        )
    except Exception as exc:  # noqa: BLE001 — caller 에 wrap 해서 raise
        raise SnapshotRestoreError(
            f"pre-restore snapshot 생성 실패 — restore 중단: {exc}"
        ) from exc

    rc, out, err = _run_git(repo, "stash", "apply", target.git_stash_sha)
    if rc != 0:
        raise SnapshotRestoreError(
            f"git stash apply {target.git_stash_sha} 실패 (rc={rc}): "
            f"{err or out or 'unknown error'}. 회복: 'git stash drop' / 수동 conflict "
            f"resolve 또는 pre-restore snapshot '{pre.id}' 활용."
        )

    return RestoreResult(
        target_id=target.id,
        pre_restore_snapshot_id=pre.id,
        applied=True,
        git_apply_stdout=out,
        git_apply_stderr=err,
    )
