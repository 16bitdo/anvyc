"""install.sh smoke test.

- bash -n syntax check (필수)
- shellcheck (설치돼 있으면, 없으면 skip)

실 네트워크 호출 (GitHub API) 은 하지 않음 — install.sh 의 정적 검증만.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).parent.parent / "install.sh"


def test_install_sh_exists() -> None:
    assert INSTALL_SH.is_file(), f"install.sh missing: {INSTALL_SH}"


def test_install_sh_is_executable() -> None:
    st = INSTALL_SH.stat()
    assert st.st_mode & 0o111, "install.sh must be executable"


def test_install_sh_bash_syntax() -> None:
    """bash -n 으로 syntax 검증."""
    proc = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_install_sh_has_strict_mode() -> None:
    """`set -euo pipefail` 강제."""
    body = INSTALL_SH.read_text()
    assert "set -euo pipefail" in body


def test_install_sh_verifies_sha256() -> None:
    """SHA256SUMS 검증 단계가 존재."""
    body = INSTALL_SH.read_text()
    assert "SHA256SUMS" in body
    assert "SHA256 mismatch" in body or "SHA256 verified" in body


@pytest.mark.skipif(
    shutil.which("shellcheck") is None,
    reason="shellcheck not installed",
)
def test_install_sh_shellcheck_passes() -> None:
    """shellcheck 가 설치돼 있으면 통과해야 함."""
    proc = subprocess.run(
        ["shellcheck", str(INSTALL_SH)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
