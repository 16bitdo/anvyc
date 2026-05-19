"""anvyc init --from-git 통합 테스트.

local bare git repo 를 fixture 로 만든 뒤 anvyc CLI 가 정상 clone 하는지 검증.
실 인터넷/SSH 접속 없음.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _anvyc(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [str(Path(sys.executable).parent / "anvyc"), *args]
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True
    )


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "anvyc-test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "anvyc-test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "HOME": "/tmp",
            "PATH": "/usr/bin:/usr/local/bin:/opt/homebrew/bin",
        },
    )


@pytest.fixture
def fake_anvyc_remote(tmp_path: Path) -> str:
    """anvyc.yaml 1건만 가진 bare git repo 를 만들고 file:// URL 반환."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "anvyc.yaml").write_text(
        "version: 1\nstorage:\n  root: '.anvyc'\ntools: {}\n"
    )
    _git("init", "-b", "main", cwd=work)
    _git("add", "anvyc.yaml", cwd=work)
    _git("commit", "-m", "initial", cwd=work)

    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(work), str(bare)],
        check=True,
        capture_output=True,
    )
    shutil.rmtree(work)
    return f"file://{bare}"


@pytest.fixture
def empty_remote(tmp_path: Path) -> str:
    """anvyc.yaml 이 없는 bare git repo (negative case)."""
    work = tmp_path / "work_no_anvyc"
    work.mkdir()
    (work / "README.md").write_text("# not anvyc\n")
    _git("init", "-b", "main", cwd=work)
    _git("add", "README.md", cwd=work)
    _git("commit", "-m", "initial", cwd=work)

    bare = tmp_path / "empty.git"
    subprocess.run(
        ["git", "clone", "--bare", str(work), str(bare)],
        check=True,
        capture_output=True,
    )
    shutil.rmtree(work)
    return f"file://{bare}"


def test_from_git_happy_path(tmp_path: Path, fake_anvyc_remote: str) -> None:
    """anvyc.yaml 가진 bare repo clone 성공 + 검증 통과."""
    target = tmp_path / "machine_b"
    target.mkdir()

    proc = _anvyc("init", "--from-git", fake_anvyc_remote, "--root", str(target))
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert (target / ".anvyc" / "anvyc.yaml").is_file()
    assert "cloned" in proc.stdout
    assert "next" in proc.stdout


def test_from_git_target_conflict_fails(
    tmp_path: Path, fake_anvyc_remote: str
) -> None:
    """target .anvyc/ 이미 존재 → exit 1 + 기존 내용 보존."""
    target = tmp_path / "machine_c"
    target.mkdir()
    (target / ".anvyc").mkdir()
    marker = target / ".anvyc" / "DO_NOT_TOUCH"
    marker.write_text("preserved\n")

    proc = _anvyc("init", "--from-git", fake_anvyc_remote, "--root", str(target))
    assert proc.returncode == 1
    assert "이미 존재" in proc.stdout
    # 기존 marker 보존
    assert marker.read_text() == "preserved\n"


def test_from_git_missing_anvyc_yaml_fails(
    tmp_path: Path, empty_remote: str
) -> None:
    """clone 됐지만 anvyc.yaml 부재 → exit 1, clone 디렉터리는 그대로."""
    target = tmp_path / "machine_d"
    target.mkdir()

    proc = _anvyc("init", "--from-git", empty_remote, "--root", str(target))
    assert proc.returncode == 1
    assert "anvyc.yaml 부재" in proc.stdout
    # .anvyc/ 디렉터리는 그대로 (사용자 검증 책임)
    assert (target / ".anvyc").is_dir()
