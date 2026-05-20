"""git init + pre-commit hook + scan-secrets 흐름."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from anvyc.core.backup import run_backup
from anvyc.storage.git import GitError, commit, init_repo, status
from tests.integration._helpers import heal_editable_pth


def _git_user_for_test(repo: Path) -> None:
    """global git config 가 없는 CI 환경 대비 — local config 설정."""
    subprocess.run(["git", "config", "user.email", "test@anvyc"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(repo), check=True)


def test_init_creates_repo_gitignore_hook(isolated_env: dict[str, Path]) -> None:
    root = isolated_env["root"]
    init_repo(root)
    assert (root / ".git").is_dir()
    gi = (root / ".gitignore").read_text()
    assert "local-backups" in gi
    assert "reports" in gi
    hook = root / ".git/hooks/pre-commit"
    assert hook.is_file()
    assert hook.stat().st_mode & 0o111  # executable


def test_status_after_init_lists_untracked(isolated_env: dict[str, Path]) -> None:
    init_repo(isolated_env["root"])
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    out = status(isolated_env["root"])
    # backups/, anvyc.yaml 등 untracked 표시
    assert "anvyc.yaml" in out or "backups" in out


def test_commit_creates_revision(isolated_env: dict[str, Path]) -> None:
    init_repo(isolated_env["root"])
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    _git_user_for_test(isolated_env["root"])
    commit(isolated_env["root"], "initial")
    # HEAD 가 생겼는지
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(isolated_env["root"]),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert len(result.stdout.strip()) == 40


def test_commit_with_no_changes_does_not_error(isolated_env: dict[str, Path]) -> None:
    init_repo(isolated_env["root"])
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    _git_user_for_test(isolated_env["root"])
    commit(isolated_env["root"], "first")
    # 다시 — 변경 없음
    out = commit(isolated_env["root"], "noop")
    assert "nothing to commit" in out


def test_pre_commit_hook_blocks_raw_secret(isolated_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """pre-commit hook 이 anvyc 를 호출해 secret 차단.

    hook 안에서 `command -v anvyc` 가 실패하면 silent skip 으로 빠지므로,
    venv 의 anvyc 실행파일 절대 경로를 ANVYC_BIN env var 로 전달한다.
    """
    heal_editable_pth()
    venv_anvyc = Path(sys.executable).parent / "anvyc"
    assert venv_anvyc.exists(), f"venv anvyc not found at {venv_anvyc}"
    monkeypatch.setenv("ANVYC_BIN", str(venv_anvyc))

    root = isolated_env["root"]
    init_repo(root)
    run_backup(root=root, config_path=isolated_env["config"])
    _git_user_for_test(root)
    commit(root, "base")
    (root / "leaked.env").write_text("AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF\n")
    with pytest.raises(GitError):
        commit(root, "bad")
