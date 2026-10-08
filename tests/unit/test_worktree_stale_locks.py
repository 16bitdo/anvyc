"""worktree-stale-locks — Claude 세션이 정리 없이 끝나며 남긴 worktree 잠금 탐지.

계기 — 2026-10-06: pulseforge 의 worktree 가 8/5 Claude 세션 잠금(pid 89657 — 이미 종료)으로
두 달간 남아 `git worktree remove` 를 막았다. 진짜 git 저장소에 진짜 `git worktree lock` 을 건다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from anvyc.checks import worktree_stale_locks as mod
from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.worktree_stale_locks import WorktreeStaleLocksCheck


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("x\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", str(wt), "-b", "probe")
    return root, wt


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _c_locale_start(pid: int) -> str:
    """검사 대상 코드와 독립적으로 구한 시작 시각(Claude 잠금 사유와 같은 C 로캘 형식)."""
    out = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        capture_output=True, text=True, check=True, env={**os.environ, "LC_ALL": "C"},
    ).stdout
    return " ".join(out.split())


def _warnings(monkeypatch: pytest.MonkeyPatch, projects: list[Path]) -> list[Path]:
    monkeypatch.setattr(mod, "_projects", lambda: projects)
    results = WorktreeStaleLocksCheck().run(CheckContext())
    return [r.location.resolve() for r in results if r.severity == Severity.WARNING and r.location]


def test_dead_session_lock_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, wt = _repo_with_worktree(tmp_path)
    reason = f"claude session probe (pid {_dead_pid()} start Wed Jan  1 00:00:00 2025)"
    _git(root, "worktree", "lock", "--reason", reason, str(wt))

    assert _warnings(monkeypatch, [root]) == [wt.resolve()]


def test_live_session_lock_is_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, wt = _repo_with_worktree(tmp_path)
    me = os.getpid()
    reason = f"claude session probe (pid {me} start {_c_locale_start(me)})"
    _git(root, "worktree", "lock", "--reason", reason, str(wt))

    assert _warnings(monkeypatch, [root]) == []


def test_foreign_lock_reason_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """사람이 의도로 건 잠금(형식이 다른 사유)은 판정하지 않는다."""
    root, wt = _repo_with_worktree(tmp_path)
    _git(root, "worktree", "lock", "--reason", "keep for release", str(wt))

    assert _warnings(monkeypatch, [root]) == []


def test_same_repo_found_twice_reports_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """프로젝트 탐색은 linked worktree 도 프로젝트로 잡는다 — 같은 저장소를 두 번 세지 않는다."""
    root, wt = _repo_with_worktree(tmp_path)
    reason = f"claude session probe (pid {_dead_pid()} start Wed Jan  1 00:00:00 2025)"
    _git(root, "worktree", "lock", "--reason", reason, str(wt))

    assert _warnings(monkeypatch, [root, wt]) == [wt.resolve()]


def test_unusable_ps_reports_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ps 가 실패하면 「프로세스 없음」과 구별할 수 없다 — 살아 있는 세션까지 전부 오탐하므로
    판정하지 않는다(무오탐). 점검은 ps 로 자기 자신을 먼저 본다."""
    root, wt = _repo_with_worktree(tmp_path)
    reason = f"claude session probe (pid {_dead_pid()} start Wed Jan  1 00:00:00 2025)"
    _git(root, "worktree", "lock", "--reason", reason, str(wt))
    monkeypatch.setattr(mod, "process_start", lambda pid: None)

    assert _warnings(monkeypatch, [root]) == []


def test_registered_in_doctor_registry() -> None:
    from anvyc.core.doctor import _REGISTRY

    assert "worktree-stale-locks" in _REGISTRY
