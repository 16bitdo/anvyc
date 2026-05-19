"""anvyc tools list --json 통합 테스트 (P5, v0.8.0)."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path


def _anvyc(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [str(Path(sys.executable).parent / "anvyc"), *args]
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True
    )


def test_tools_list_json_schema(tmp_path: Path) -> None:
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    cfg.parent.mkdir()
    cfg.write_text("version: 1\ntools: {}\n")

    proc = _anvyc("tools", "list", "--config", str(cfg), "--json", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert isinstance(data, list)
    # 9 tools (shell/git/aws/gh/cursor/claude/iterm2/pulumi/dev_env)
    assert len(data) >= 9
    tool_names = {row["tool"] for row in data}
    assert {"shell", "git", "aws", "gh", "cursor", "claude", "iterm2", "pulumi", "dev_env"} <= tool_names
    # 각 row schema
    for row in data:
        assert set(row.keys()) == {"tool", "enabled", "detected", "files", "secrets"}
        assert isinstance(row["enabled"], bool)
        assert isinstance(row["detected"], bool)
        assert isinstance(row["files"], int)
        assert isinstance(row["secrets"], int)


def test_tools_list_json_reflects_config(tmp_path: Path) -> None:
    """tools.git.enabled=false 가 JSON output 에 반영."""
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    cfg.parent.mkdir()
    cfg.write_text(
        textwrap.dedent("""\
        version: 1
        tools:
          git: {enabled: false}
          shell:
            enabled: true
            files:
              - "~/.zshrc"
              - "~/.zprofile"
        """)
    )

    proc = _anvyc("tools", "list", "--config", str(cfg), "--json", cwd=tmp_path)
    data = json.loads(proc.stdout)
    rows = {row["tool"]: row for row in data}
    assert rows["git"]["enabled"] is False
    assert rows["shell"]["enabled"] is True
    assert rows["shell"]["files"] == 2
