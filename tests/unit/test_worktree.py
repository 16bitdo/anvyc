"""worktree 룰 연결 — `anvyc worktree add` 의 핵심 로직.

문제: `git worktree add` 로 만든 트리에는 에이전트가 읽어야 할 룰이 전부 빠진다.
`CLAUDE.md`·`.cursor/rules`·`.cursor/skills` 는 대개 gitignore 대상이라
체크아웃되지 않는다. 정작 rule 18 은 worktree-per-task 격리를 권장하므로,
권장을 따르면 그 권장을 담은 룰이 사라진다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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
