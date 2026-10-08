"""worktree 룰 연결 — `anvyc worktree add` 의 핵심 로직.

문제: `git worktree add` 로 만든 트리에는 에이전트가 읽어야 할 룰이 전부 빠진다.
`CLAUDE.md`·`.cursor/rules`·`.cursor/skills` 는 대개 gitignore 대상이라
체크아웃되지 않는다. 정작 rule 18 은 worktree-per-task 격리를 권장하므로,
권장을 따르면 그 권장을 담은 룰이 사라진다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from anvyc.core.project_info import ProjectInfo
from anvyc.core.worktree import (
    LINK_TARGETS,
    is_worktree,
    link_rules,
    missing_rule_links,
)


def _origin(tmp: Path) -> Path:
    """룰 자산을 가진 원본 저장소."""
    root = tmp / "origin"
    (root / ".cursor" / "rules").mkdir(parents=True)
    (root / ".cursor" / "skills").mkdir(parents=True)
    (root / ".cursor" / "rules" / "20-aws.mdc").write_text("rule\n", encoding="utf-8")
    (root / ".cursor" / "skills" / "s.md").write_text("skill\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("index v1\n", encoding="utf-8")
    (root / ".envrc").write_text("export X=1\n", encoding="utf-8")
    return root


class TestLinkRules:
    def test_links_rule_assets(self, tmp_path: Path) -> None:
        origin, wt = _origin(tmp_path), tmp_path / "wt"
        wt.mkdir()

        results = link_rules(origin, wt)
        linked = {r.name for r in results if r.status == "linked"}

        assert linked == {".cursor/rules", ".cursor/skills", "CLAUDE.md"}
        assert (wt / ".cursor" / "rules" / "20-aws.mdc").read_text() == "rule\n"
        assert (wt / "CLAUDE.md").read_text() == "index v1\n"

    def test_cursor_stays_a_real_directory(self, tmp_path: Path) -> None:
        """`.gitignore` 의 `.cursor/` 는 디렉터리만 매칭한다.

        `.cursor` 자체를 symlink 하면 파일로 취급돼 ignore 를 빠져나가고
        `?? .cursor` 로 워킹트리를 더럽힌다(2026-08-25 실측).
        """
        origin, wt = _origin(tmp_path), tmp_path / "wt"
        wt.mkdir()
        link_rules(origin, wt)

        assert (wt / ".cursor").is_dir()
        assert not (wt / ".cursor").is_symlink()
        assert (wt / ".cursor" / "rules").is_symlink()

    def test_origin_update_is_reflected(self, tmp_path: Path) -> None:
        """복사가 아니라 링크 — 원본이 갱신되면 즉시 따라온다."""
        origin, wt = _origin(tmp_path), tmp_path / "wt"
        wt.mkdir()
        link_rules(origin, wt)

        (origin / "CLAUDE.md").write_text("index v2\n", encoding="utf-8")

        assert (wt / "CLAUDE.md").read_text() == "index v2\n"

    def test_existing_file_is_left_alone(self, tmp_path: Path) -> None:
        """사람이 의도적으로 둔 파일을 덮어쓰지 않는다."""
        origin, wt = _origin(tmp_path), tmp_path / "wt"
        wt.mkdir()
        (wt / "CLAUDE.md").write_text("mine\n", encoding="utf-8")

        results = link_rules(origin, wt)
        status = {r.name: r.status for r in results}

        assert status["CLAUDE.md"] == "exists"
        assert (wt / "CLAUDE.md").read_text() == "mine\n"

    def test_absent_origin_asset_is_reported(self, tmp_path: Path) -> None:
        origin, wt = tmp_path / "bare", tmp_path / "wt"
        origin.mkdir()
        wt.mkdir()

        status = {r.name: r.status for r in link_rules(origin, wt)}

        assert set(status) == set(LINK_TARGETS)
        assert all(v == "absent" for v in status.values())

    def test_envrc_is_notice_only(self, tmp_path: Path) -> None:
        """direnv 승인은 경로별 보안 경계다 — 자동으로 열지 않는다."""
        origin, wt = _origin(tmp_path), tmp_path / "wt"
        wt.mkdir()

        results = link_rules(origin, wt)
        envrc = [r for r in results if r.name == ".envrc"]

        assert len(envrc) == 1
        assert envrc[0].status == "notice"
        assert not (wt / ".envrc").exists()

    def test_venv_is_notice_with_dev_install_hint(self, tmp_path: Path) -> None:
        """`.venv` 는 링크하지 않는다 — 안에 절대경로가 박혀 있어 링크하면 깨진다.

        대신 이 worktree 에서 새로 만들라고 알린다. 모르고 지나치면 첫 커밋이 pre-commit 훅의
        `.venv/bin/ruff` 에서 막히고, pre-push 게이트는 조용히 skip 된다(2026-10-06 실측).
        worktree 에 `scripts/dev-install.sh` 가 있으면 그 명령을 알려 준다 — worktree 에서 돌려도
        전역 래퍼·공용 훅을 건드리지 않는다(같은 날 sandbox·실제 worktree 에서 실측).
        """
        origin, wt = _origin(tmp_path), tmp_path / "wt"
        (origin / ".venv" / "bin").mkdir(parents=True)
        (wt / "scripts").mkdir(parents=True)
        (wt / "scripts" / "dev-install.sh").write_text("#!/bin/sh\n", encoding="utf-8")

        venv = [r for r in link_rules(origin, wt) if r.name == ".venv"]

        assert len(venv) == 1
        assert venv[0].status == "notice"
        assert "bash scripts/dev-install.sh" in venv[0].detail
        assert not (wt / ".venv").exists()
        assert not (wt / ".venv").is_symlink()

    def test_venv_hint_does_not_name_a_script_the_repo_lacks(self, tmp_path: Path) -> None:
        """`--origin` 으로 다른 저장소(anvyx·rbr 등)에도 쓰인다 — 없는 스크립트를 안내하지 않는다."""
        origin, wt = _origin(tmp_path), tmp_path / "wt"
        (origin / ".venv" / "bin").mkdir(parents=True)
        wt.mkdir()

        venv = [r for r in link_rules(origin, wt) if r.name == ".venv"]

        assert len(venv) == 1
        assert venv[0].status == "notice"
        assert "dev-install.sh" not in venv[0].detail

    def test_no_venv_in_origin_means_no_venv_notice(self, tmp_path: Path) -> None:
        """원본이 venv 를 쓰지 않으면 침묵한다 — `.envrc` 와 같은 규칙."""
        origin, wt = _origin(tmp_path), tmp_path / "wt"
        wt.mkdir()

        names = {r.name for r in link_rules(origin, wt)}

        assert ".venv" not in names

    def test_direnv_is_notice_only(self, tmp_path: Path) -> None:
        """`.direnv` 도 절대경로가 박혀 있다 — `direnv allow` 가 이 worktree 에 새로 만든다."""
        origin, wt = _origin(tmp_path), tmp_path / "wt"
        (origin / ".direnv").mkdir()
        wt.mkdir()

        direnv = [r for r in link_rules(origin, wt) if r.name == ".direnv"]

        assert len(direnv) == 1
        assert direnv[0].status == "notice"
        assert "direnv allow" in direnv[0].detail
        assert not (wt / ".direnv").exists()

    def test_symlink_is_relative(self, tmp_path: Path) -> None:
        """worktree 를 옮겨도 링크가 살아 있도록 상대 경로로 건다."""
        origin, wt = _origin(tmp_path), tmp_path / "wt"
        wt.mkdir()
        link_rules(origin, wt)

        assert not Path((wt / "CLAUDE.md").readlink()).is_absolute()


class TestDetection:
    def test_missing_rule_links_lists_gaps(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()

        assert set(missing_rule_links(wt)) == set(LINK_TARGETS)

    def test_missing_rule_links_empty_after_linking(self, tmp_path: Path) -> None:
        origin, wt = _origin(tmp_path), tmp_path / "wt"
        wt.mkdir()
        link_rules(origin, wt)

        assert missing_rule_links(wt) == ()

    def test_is_worktree_distinguishes_linked_tree(self, tmp_path: Path) -> None:
        """linked worktree 는 `.git` 이 디렉터리가 아니라 파일이다."""
        root = tmp_path / "repo"
        root.mkdir()
        for argv in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "t"],
        ):
            subprocess.run(argv, cwd=root, check=True, capture_output=True)
        (root / "f.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init"], cwd=root, check=True, capture_output=True
        )
        wt = tmp_path / "wt"
        subprocess.run(
            ["git", "worktree", "add", "-q", str(wt), "-b", "probe"],
            cwd=root, check=True, capture_output=True,
        )

        assert is_worktree(wt)
        assert not is_worktree(root)


class TestDoctorCheck:
    """Phase 2 — 래퍼를 안 쓴 worktree 를 탐지한다.

    래퍼는 강제할 수 없다. 직접 `git worktree add` 를 쓰면 룰이 빠진 채 굴러가는데
    아무 신호가 없었다 — 오늘 review 에서 `.cursor` 를 손으로 복사한 상황이 그것이다.
    """

    @staticmethod
    def _info(path: Path) -> ProjectInfo:
        return ProjectInfo(
            path=str(path),
            aws_profile=None,
            gh_account=None,
            claude_account=None,
            github=None,
            pulumi=None,
        )

    def test_origin_checkout_is_silent(self, tmp_path: Path) -> None:
        """원본 체크아웃은 검증 대상이 아니다 — 잡음을 만들지 않는다."""
        from anvyc.core.project_doctor import _check_worktree_rule_links

        root = tmp_path / "repo"
        (root / ".git").mkdir(parents=True)  # 디렉터리 = 원본

        assert _check_worktree_rule_links(self._info(root)) == []

    def test_worktree_without_links_warns(self, tmp_path: Path) -> None:
        from anvyc.checks.base import Severity
        from anvyc.core.project_doctor import _check_worktree_rule_links

        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: /nowhere\n", encoding="utf-8")  # 파일 = linked

        results = _check_worktree_rule_links(self._info(wt))

        assert len(results) == 1
        assert results[0].severity is Severity.WARNING
        assert "룰 자산" in results[0].message

    def test_worktree_with_links_is_info(self, tmp_path: Path) -> None:
        from anvyc.checks.base import Severity
        from anvyc.core.project_doctor import _check_worktree_rule_links

        origin, wt = _origin(tmp_path), tmp_path / "wt"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: /nowhere\n", encoding="utf-8")
        link_rules(origin, wt)

        results = _check_worktree_rule_links(self._info(wt))

        assert len(results) == 1
        assert results[0].severity is Severity.INFO


class TestGitignoreDepthVariants:
    """저장소마다 gitignore 패턴 깊이가 다르다 — 링크 위치만으로는 덮이지 않는다.

    `.cursor/`(한 층) 저장소는 `.cursor` 를 실제 디렉터리로 두면 하위 symlink 가
    ignore 된다. 그런데 `.cursor/rules/`(두 층)를 쓰는 저장소에서는 `rules` 가
    symlink 라 디렉터리 패턴을 빠져나가 `?? .cursor/` 가 남는다(2026-08-25 실측:
    role-based-ruleset). 공용 exclude 에 슬래시 없는 규칙을 더해 덮는다.
    """

    @staticmethod
    def _repo(tmp: Path, ignore_body: str) -> Path:
        root = tmp / "repo"
        root.mkdir()
        for argv in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "t"],
        ):
            subprocess.run(argv, cwd=root, check=True, capture_output=True)
        (root / ".gitignore").write_text(ignore_body, encoding="utf-8")
        (root / ".cursor" / "rules").mkdir(parents=True)
        (root / ".cursor" / "skills").mkdir(parents=True)
        (root / ".cursor" / "rules" / "r.mdc").write_text("r\n", encoding="utf-8")
        (root / "CLAUDE.md").write_text("idx\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init"], cwd=root, check=True, capture_output=True
        )
        return root

    def _add_worktree(self, root: Path, wt: Path) -> None:
        subprocess.run(
            ["git", "worktree", "add", "-q", str(wt), "-b", "probe"],
            cwd=root, check=True, capture_output=True,
        )

    @staticmethod
    def _status(path: Path) -> str:
        return subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()

    def test_one_level_pattern_stays_clean(self, tmp_path: Path) -> None:
        root = self._repo(tmp_path, ".cursor/\nCLAUDE.md\n")
        wt = tmp_path / "wt"
        self._add_worktree(root, wt)

        link_rules(root, wt)

        assert self._status(wt) == ""

    def test_two_level_pattern_stays_clean(self, tmp_path: Path) -> None:
        """회귀의 본체 — 링크 위치를 낮추는 것만으로는 이 형태를 덮지 못했다."""
        root = self._repo(tmp_path, ".cursor/rules/\n.cursor/skills/\nCLAUDE.md\n")
        wt = tmp_path / "wt"
        self._add_worktree(root, wt)

        link_rules(root, wt)

        assert self._status(wt) == ""

    def test_origin_is_unaffected(self, tmp_path: Path) -> None:
        """공용 exclude 를 건드리지만 원본 동작은 바뀌지 않는다.

        우리가 적는 경로는 원본이 이미 ignore 하는 대상이라 중복 규칙이 된다.
        """
        root = self._repo(tmp_path, ".cursor/rules/\n.cursor/skills/\nCLAUDE.md\n")
        wt = tmp_path / "wt"
        self._add_worktree(root, wt)

        before = self._status(root)
        link_rules(root, wt)

        assert self._status(root) == before == ""


# 2026-10-06 pulseforge 실측 — Claude 세션이 정리 없이 끝나며 남긴 잠금 사유 원문.
_REAL_CLAUDE_REASON = "claude session phase3b1-web-ui (pid 89657 start Wed Aug  5 06:36:11 2026)"

_PORCELAIN = (
    "worktree /repo\n"
    "HEAD 1111111111111111111111111111111111111111\n"
    "branch refs/heads/main\n"
    "\n"
    "worktree /wt/claude\n"
    "HEAD 2222222222222222222222222222222222222222\n"
    "branch refs/heads/feat/a\n"
    f"locked {_REAL_CLAUDE_REASON}\n"
    "\n"
    "worktree /wt/plain\n"
    "HEAD 3333333333333333333333333333333333333333\n"
    "branch refs/heads/feat/b\n"
    "\n"
    "worktree /wt/bare-lock\n"
    "HEAD 4444444444444444444444444444444444444444\n"
    "detached\n"
    "locked\n"
    "\n"
    "worktree /wt/gone\n"
    "HEAD 5555555555555555555555555555555555555555\n"
    "branch refs/heads/feat/c\n"
    "locked keep for release\n"
    "prunable gitdir file points to non-existent location\n"
    "\n"
)


def _dead_pid() -> int:
    """방금 끝난 프로세스의 pid — 테스트 동안 재사용될 가능성은 무시할 만하다."""
    import sys

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


class TestStaleLockParsing:
    """2026-10-06: pulseforge worktree 가 8/5 Claude 세션 잠금(pid 89657 — 이미 종료)으로 두 달간
    남아 `git worktree remove` 를 막았다. 잠금은 세션이 정리 없이 끝나면 그대로 남고 신호가 없다."""

    def test_locked_worktrees_reads_reason_and_branch(self) -> None:
        from anvyc.core.worktree import LockedWorktree, locked_worktrees

        assert locked_worktrees(_PORCELAIN) == [
            LockedWorktree(Path("/wt/claude"), "feat/a", _REAL_CLAUDE_REASON),
            LockedWorktree(Path("/wt/bare-lock"), None, ""),
            LockedWorktree(Path("/wt/gone"), "feat/c", "keep for release"),
        ]

    def test_main_worktree_in_is_first_entry(self) -> None:
        from anvyc.core.worktree import main_worktree_in

        assert main_worktree_in(_PORCELAIN) == Path("/repo")
        assert main_worktree_in("") is None

    def test_parse_claude_lock_accepts_only_claude_format(self) -> None:
        from anvyc.core.worktree import ClaudeLock, parse_claude_lock

        assert parse_claude_lock(_REAL_CLAUDE_REASON) == ClaudeLock(
            "phase3b1-web-ui", 89657, "Wed Aug  5 06:36:11 2026"
        )
        assert parse_claude_lock("claude session my task (pid 7 start Thu Oct  8 09:43:11 2026)") == (
            ClaudeLock("my task", 7, "Thu Oct  8 09:43:11 2026")
        )
        for foreign in ("", "keep for release", "claude session x (pid abc start now)"):
            assert parse_claude_lock(foreign) is None, foreign

    def test_stale_lock_reason_dead_alive_and_reused_pid(self) -> None:
        from anvyc.core.worktree import ClaudeLock, stale_lock_reason

        lock = ClaudeLock("s", 89657, "Wed Aug  5 06:36:11 2026")
        assert "없음" in (stale_lock_reason(lock, lambda pid: None) or "")
        # 같은 시각이면 살아 있는 세션 — ps 의 공백 차이는 무시한다
        assert stale_lock_reason(lock, lambda pid: "Wed Aug  5 06:36:11 2026    ") is None
        # pid 는 살아 있지만 시작 시각이 다르다 = 그 pid 를 다른 프로세스가 재사용
        assert "다른 프로세스" in (
            stale_lock_reason(lock, lambda pid: "Thu Oct  8 09:43:11 2026") or ""
        )

    def test_process_start_is_c_locale_regardless_of_caller(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2026-10-07 실측: ko_KR 로캘의 `ps -o lstart` 는 「2026년 10월  8일 목요일 …」이다.
        잠금 사유는 C 로캘 형식이라 그대로 비교하면 살아 있는 세션이 전부 「다른 프로세스」가 된다."""
        import os
        import re

        from anvyc.core.worktree import process_start

        monkeypatch.setenv("LANG", "ko_KR.UTF-8")
        monkeypatch.setenv("LC_ALL", "ko_KR.UTF-8")
        start = process_start(os.getpid())
        assert start is not None
        assert re.fullmatch(r"[A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2} \d{2}:\d{2}:\d{2} \d{4}", start), start

    def test_process_start_of_finished_process_is_none(self) -> None:
        from anvyc.core.worktree import process_start

        assert process_start(_dead_pid()) is None
