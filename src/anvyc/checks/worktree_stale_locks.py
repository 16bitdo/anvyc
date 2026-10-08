"""worktree-stale-locks check (L2 관측, read-only).

Claude 세션은 자기 worktree 를 `git worktree lock` 으로 잠그고, 정리 없이 끝나면 잠금이
남는다. 잠긴 worktree 는 `git worktree remove`·`prune` 이 거부하는데 아무 신호가 없다 —
2026-10-06 pulseforge 에서 8/5 세션(pid 89657, 이미 종료)의 잠금이 두 달간 정리를 막았다.

판정만 하고 해제하지 않는다. 그 worktree 에만 있는 무시 파일(그날 `.superpowers/sdd/` 42개)이
있을 수 있어 사람이 보존을 확인해야 한다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.project_discovery import discover_projects
from anvyc.core.worktree import (
    ClaudeLock,
    LockedWorktree,
    locked_worktrees,
    main_worktree_in,
    parse_claude_lock,
    process_start,
    stale_lock_reason,
)


def _projects() -> list[Path]:
    """관측 대상 프로젝트. discover_projects 위임(테스트 patch 지점)."""
    return discover_projects()


def _worktree_list(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


class WorktreeStaleLocksCheck:
    """L2(read-only): 끝난 Claude 세션이 남긴 worktree 잠금."""

    name = "worktree-stale-locks"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        # ps 가 실패하면 「프로세스 없음」과 구별할 수 없다 — 자기 자신도 못 보면 판정하지 않는다.
        if process_start(os.getpid()) is None:
            return []
        seen: set[Path] = set()
        results: list[CheckResult] = []
        for repo in _projects():
            porcelain = _worktree_list(repo)
            main = main_worktree_in(porcelain) if porcelain else None
            if porcelain is None or main is None or main in seen:
                continue  # 프로젝트 탐색은 linked worktree 도 잡는다 — 저장소는 한 번만
            seen.add(main)
            for wt in locked_worktrees(porcelain):
                lock = parse_claude_lock(wt.reason)
                if lock is None:
                    continue
                why = stale_lock_reason(lock, process_start)
                if why is not None:
                    results.append(self._stale(main, wt, lock, why))
        return results

    def _stale(self, main: Path, wt: LockedWorktree, lock: ClaudeLock, why: str) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            severity=Severity.WARNING,
            message=(
                f"{main.name}: worktree {wt.path} ({wt.branch or 'detached'}) 가 끝난 Claude "
                f"세션의 잠금으로 남아 있다 — {why} · 세션 {lock.session} · 시작 {lock.start}. "
                "잠긴 worktree 는 remove·prune 이 거부한다"
            ),
            location=wt.path,
            suggestion=(
                f"그 worktree 에만 있는 무시 파일부터 확인(git -C {wt.path} status --ignored) → "
                f"git -C {main} worktree unlock {wt.path} → 필요하면 worktree remove"
            ),
        )
