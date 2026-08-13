"""`collect_project_info()` 의 git worktree `.git` 파일 포인터 해석 (Task 14).

git (linked) worktree 에서 `.git` 은 디렉터리가 아니라 `gitdir: <path>` 포인터
파일이다. 기존 코드는 `git_dir.is_dir()` 로만 판정해 worktree 에서는 `github`
가 항상 `None` 이 됐고, 그 결과 `gh_account_routing`·`gh_identity_actual`·
`commit_identity_actual`·`github_remote_parseable` 등 github 의존 doctor check
전부가 조용히 스킵됐다.

레이아웃은 실제 `git worktree add` 로 만든 실측(2026-08-13,
`/tmp/anvyc-wt-test`)을 그대로 파일로 흉내낸다 — `git` 프로세스 호출 없이,
offline 원칙과 동일하게 검증한다:

- `.git` 파일 내용: `gitdir: <절대경로>\\n` (실측: 항상 절대경로)
- 포인터 대상 디렉터리의 `commondir` 파일 내용: `../..\\n` (상대경로, 본체 `.git` 로)
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

from anvyc.core.project_info import collect_project_info

_ORIGIN_URL = "git@github.com:acme/widgets.git"
_EXPECTED_REMOTE = {
    "name": "origin",
    "url": _ORIGIN_URL,
    "host": "github.com",
    "owner": "acme",
    "repo": "widgets",
    "ssh_alias": None,
    "protocol": "ssh",
}


def _write_git_config(git_dir: Path, url: str = _ORIGIN_URL) -> None:
    """`git_dir/config` 에 origin remote 하나를 쓴다 (`test_git_remote_util.py` 와 동일 스타일)."""
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "config").write_text(
        textwrap.dedent(
            f"""\
            [core]
                repositoryformatversion = 0
            [remote "origin"]
                url = {url}
                fetch = +refs/heads/*:refs/remotes/origin/*
            """
        ),
        encoding="utf-8",
    )


def _make_linked_worktree(tmp_path: Path, *, relative_pointer: bool = False) -> Path:
    """본체 `main/.git` + worktree-private gitdir(`commondir` 포함) + `wt/.git` 포인터 파일을 실측 그대로 구성.

    반환값은 worktree 루트(`wt`) — 이 경로를 `collect_project_info()` 에 넘긴다.
    """
    main_git = tmp_path / "main" / ".git"
    _write_git_config(main_git)

    worktree_gitdir = main_git / "worktrees" / "wt"
    worktree_gitdir.mkdir(parents=True)
    (worktree_gitdir / "commondir").write_text("../..\n", encoding="utf-8")

    wt = tmp_path / "wt"
    wt.mkdir()
    pointer = os.path.relpath(worktree_gitdir, wt) if relative_pointer else str(worktree_gitdir)
    (wt / ".git").write_text(f"gitdir: {pointer}\n", encoding="utf-8")
    return wt


class TestWorktreeGitFilePointer:
    def test_absolute_gitdir_pointer_resolves_remote_from_common_config(
        self, tmp_path: Path
    ) -> None:
        """실측 그대로: 절대경로 `gitdir:` 포인터 + `commondir` → 본체 config 의 remote."""
        wt = _make_linked_worktree(tmp_path)

        info = collect_project_info(wt)

        assert info.github == [_EXPECTED_REMOTE]

    def test_relative_gitdir_pointer_resolves_relative_to_dotgit_parent(
        self, tmp_path: Path
    ) -> None:
        """`gitdir:` 값이 상대경로면 `.git` 파일이 있는 디렉터리(worktree 루트) 기준으로 해석한다.

        cwd 기준으로 잘못 해석하면(혹은 아예 처리 안 하면) 이 테스트는 실패한다 —
        pytest 실행 cwd 는 이 파일 기준 상대경로와 다르므로 우연히 통과할 수 없다.
        """
        wt = _make_linked_worktree(tmp_path, relative_pointer=True)
        assert (wt / ".git").read_text(encoding="utf-8").startswith("gitdir: ..")

        info = collect_project_info(wt)

        assert info.github == [_EXPECTED_REMOTE]

    def test_existing_directory_git_still_works(self, tmp_path: Path) -> None:
        """회귀 — `.git` 이 (worktree 아닌) 일반 디렉터리인 기존 경로는 그대로 동작한다."""
        proj = tmp_path / "proj"
        _write_git_config(proj / ".git")

        info = collect_project_info(proj)

        assert info.github == [_EXPECTED_REMOTE]

    def test_gitdir_pointer_to_nonexistent_path_yields_none_without_raising(
        self, tmp_path: Path
    ) -> None:
        """포인터 대상이 존재하지 않아도(파손/이관된 worktree) 예외 없이 github 는 None."""
        wt = tmp_path / "wt"
        wt.mkdir()
        missing = tmp_path / "does" / "not" / "exist"
        (wt / ".git").write_text(f"gitdir: {missing}\n", encoding="utf-8")

        info = collect_project_info(wt)

        assert info.github is None

    def test_dotgit_file_without_gitdir_prefix_yields_none_without_raising(
        self, tmp_path: Path
    ) -> None:
        """`.git` 이 파일이지만 `gitdir:` 형식이 아니면(손상/알 수 없는 포맷) 예외 없이 None."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / ".git").write_text("not-a-gitdir-pointer\n", encoding="utf-8")

        info = collect_project_info(wt)

        assert info.github is None

    def test_dotgit_file_empty_yields_none_without_raising(self, tmp_path: Path) -> None:
        """`.git` 파일이 완전히 비어 있어도(파손) 예외 없이 None."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / ".git").write_text("", encoding="utf-8")

        info = collect_project_info(wt)

        assert info.github is None

    def test_gitdir_without_commondir_uses_gitdir_itself(self, tmp_path: Path) -> None:
        """commondir 파일이 없는 gitdir(비-worktree gitdir) → 포인터 대상 자체의 config 를 쓴다.

        `.git` 파일 포인터 형식 자체는 worktree 전용이 아니다(예: git submodule 도
        동일 형식) — commondir 이 없으면 gitdir 자체가 이미 독립된 config 를 가진
        디렉터리라고 보고 그대로 사용한다.
        """
        gitdir = tmp_path / "external-gitdir"
        _write_git_config(gitdir)

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        assert not (gitdir / "commondir").exists()

        info = collect_project_info(proj)

        assert info.github == [_EXPECTED_REMOTE]
