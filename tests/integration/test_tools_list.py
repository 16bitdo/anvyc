"""anvyc tools list 통합 테스트."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def _anvyc(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [str(Path(sys.executable).parent / "anvyc"), *args]
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True
    )


def _write_yaml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body))


def test_tools_list_default_all_enabled(tmp_path: Path) -> None:
    """tools 미정의 yaml → 모든 8 도구가 enabled ✓ 로 표시."""
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    _write_yaml(cfg, "version: 1\ntools: {}\n")

    proc = _anvyc("tools", "list", "--config", str(cfg), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    # 8 도구 모두 존재
    for tool in ("shell", "git", "aws", "gh", "pulumi", "cursor", "claude", "iterm2"):
        assert tool in proc.stdout, f"missing tool row: {tool}"
    # footer 안내
    assert "v0.7+" in proc.stdout
    assert "vscode" in proc.stdout


def test_tools_list_partial_disabled(tmp_path: Path) -> None:
    """yaml 에서 git 만 disabled → git 행에 disabled 표식 (✗)."""
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    _write_yaml(
        cfg,
        """\
        version: 1
        tools:
          git:
            enabled: false
          shell:
            enabled: true
            files:
              - "~/.zshrc"
        """,
    )

    proc = _anvyc("tools", "list", "--config", str(cfg), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    # git 행에 ✗ (그 외 도구는 ✓ default), shell 행에 files=1
    lines = proc.stdout.splitlines()
    git_line = next((line for line in lines if " git " in f" {line} "), None)
    shell_line = next((line for line in lines if " shell " in f" {line} "), None)
    assert git_line is not None
    assert shell_line is not None
    assert "✗" in git_line
    # shell 의 files 수 1
    assert "1" in shell_line
