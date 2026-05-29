"""anvyc tools list --json 통합 테스트 (P5, v0.8.0)."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from tests.integration._helpers import run_anvyc as _anvyc


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
    # 각 row schema — 기존 키(하위호환) + AdapterMeta 키(additive, PR2)
    expected_keys = {
        "tool", "label", "category", "summary",
        "enabled", "detected", "files", "secrets",
        "includes", "excludes", "default_enabled", "config_kind", "since",
    }
    for row in data:
        assert set(row.keys()) == expected_keys
        assert isinstance(row["enabled"], bool)
        assert isinstance(row["detected"], bool)
        assert isinstance(row["files"], int)
        assert isinstance(row["secrets"], int)
        assert isinstance(row["label"], str) and row["label"]
        assert isinstance(row["summary"], str) and row["summary"]
        assert isinstance(row["category"], str) and row["category"]
        assert isinstance(row["includes"], list)
        assert isinstance(row["excludes"], list)
        assert isinstance(row["default_enabled"], bool)
        assert row["config_kind"] in {"files", "structured"}
        assert isinstance(row["since"], str) and row["since"]

    # 메타 값이 AdapterMeta SoT 를 반영하는지 — 대표 표본
    rows = {row["tool"]: row for row in data}
    assert rows["aws"]["label"] == "AWS CLI"
    assert rows["aws"]["category"] == "cloud"
    assert "~/.aws/config" in rows["aws"]["includes"]
    assert rows["dev_env"]["default_enabled"] is False
    assert rows["shell"]["default_enabled"] is True


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
