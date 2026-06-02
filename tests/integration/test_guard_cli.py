"""anvyc guard CLI 통합 테스트."""
from __future__ import annotations

import subprocess
from pathlib import Path

from tests.integration._helpers import run_anvyc


def _git_repo_with_origin(path: Path, remote: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True)
    return path


def test_guard_install_dry_run_lists_targets(tmp_path: Path) -> None:
    repo = _git_repo_with_origin(tmp_path / "proj", "git@github.com:16bitdo/proj.git")
    proc = run_anvyc("guard", "install", "--project", str(repo), "--dry-run", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "proj" in proc.stdout
    assert not (repo / ".git" / "hooks" / "pre-push").exists()  # dry-run: 미설치


def test_guard_install_writes_hook(tmp_path: Path) -> None:
    repo = _git_repo_with_origin(tmp_path / "proj", "git@github.com:16bitdo/proj.git")
    proc = run_anvyc("guard", "install", "--project", str(repo), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    hook = repo / ".git" / "hooks" / "pre-push"
    assert hook.is_file()
    assert "anvyc-pr-guard" in hook.read_text()


def test_guard_install_no_target_dir_exit0(tmp_path: Path) -> None:
    """존재하지 않는/비-git --project → exit 0 + 안내(typo silent-success 회피)."""
    proc = run_anvyc("guard", "install", "--project", str(tmp_path / "nope"), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "대상 repo 없음" in proc.stdout
