"""Workspace snapshot (작업 회복) — CP-4 (anvyc#29) 의 핵심.

autopilot 의 실수 (브랜치 30 파일 수정 등) 를 명시적 snapshot 으로 되돌리기
위한 capture 단. 본 모듈은 1/3 PR 의 create 만 구현; list/diff (2/3),
restore (3/3) 는 별도 PR.

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
    """`git stash create` → ref 로 anchor. (stash_ref, stash_sha) 반환.

    working tree 가 clean 이면 (str(), str()) → (None, None) 반환.
    """
    rc, sha, _err = _run_git(repo, "stash", "create")
    if rc != 0 or not sha:
        return None, None
    ref = f"{STASH_REF_PREFIX}/{snapshot_id}"
    rc, _, err = _run_git(repo, "update-ref", ref, sha)
    if rc != 0:
        # ref 갱신 실패 — sha 만 반환 (caller 가 보존 결정).
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
