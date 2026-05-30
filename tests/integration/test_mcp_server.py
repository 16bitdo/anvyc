"""anvyc MCP server dispatch 테스트 (P6, v0.9.0).

[mcp] extra 미설치 환경에서는 importorskip 로 자동 skip.
실제 stdio round-trip 은 manual smoke (Claude Code/Cursor 통합 시점).
본 파일은 _dispatch handler 의 unit-level 검증.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

pytest.importorskip("mcp")  # [mcp] extra 미설치 시 모듈 전체 skip


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body))


def test_dispatch_project_show(tmp_path: Path) -> None:
    from anvyc.mcp.server import _dispatch

    proj = tmp_path / "p"
    _write(
        proj / ".envrc",
        "export AWS_PROFILE=test-profile\n"
        'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n',
    )
    _write(
        proj / ".git" / "config",
        '[remote "origin"]\n    url = git@github.com:o/r.git\n',
    )

    result = _dispatch("project_show", {"path": str(proj)})

    assert result["aws_profile"] == "test-profile"
    assert result["gh_account"] == "16bitdo"
    assert result["github"][0]["owner"] == "o"


def test_dispatch_project_show_default_redaction(tmp_path: Path) -> None:
    """D11c default — secret 패턴 매칭 → ***REDACTED***."""
    from anvyc.mcp.server import _dispatch

    proj = tmp_path / "p"
    _write(
        proj / ".envrc",
        "export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
    )

    result = _dispatch("project_show", {"path": str(proj)})
    assert result["dev_env"]["GITHUB_TOKEN"] == "***REDACTED***"


def test_dispatch_project_show_reveal_secrets(tmp_path: Path) -> None:
    """reveal_secrets=True 시 raw 값 노출."""
    from anvyc.mcp.server import _dispatch

    proj = tmp_path / "p"
    _write(
        proj / ".envrc",
        "export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
    )

    result = _dispatch(
        "project_show", {"path": str(proj), "reveal_secrets": True}
    )
    assert result["dev_env"]["GITHUB_TOKEN"].startswith("ghp_")


def test_dispatch_project_list(tmp_path: Path) -> None:
    from anvyc.mcp.server import _dispatch

    docs = tmp_path / "docs"
    docs.mkdir()
    _write(docs / "a" / ".git" / "config", "")
    _write(docs / "b" / "Pulumi.yaml", "name: b\nruntime: python\n")

    result = _dispatch("project_list", {"roots": [str(docs)]})
    assert isinstance(result, list)
    assert len(result) == 2


def test_dispatch_project_doctor(tmp_path: Path) -> None:
    from anvyc.mcp.server import _dispatch

    proj = tmp_path / "p"
    _write(proj / "Pulumi.yaml", "name: p\nruntime: python\n")

    result = _dispatch("project_doctor", {"path": str(proj)})
    assert result["path"].endswith("/p")
    assert any(r["check_name"] == "pulumi_stacks_valid" for r in result["results"])


def test_dispatch_doctor() -> None:
    """global doctor — 적어도 results array 반환."""
    from anvyc.mcp.server import _dispatch

    result = _dispatch("doctor", {"only": ["venv-hidden-flag"]})
    assert "results" in result
    assert isinstance(result["results"], list)


def test_dispatch_tools_list() -> None:
    from anvyc.mcp.server import _dispatch

    result = _dispatch("tools_list", {})
    assert isinstance(result, list)
    # 9 adapter (shell/git/aws/gh/cursor/claude/iterm2/pulumi/dev_env)
    assert len(result) >= 9
    names = {row["tool"] for row in result}
    assert "shell" in names
    assert "dev_env" in names
    # PR2: AdapterMeta 메타 키가 MCP payload 에도 합류 (CLI 와 동일 _collect_tools_rows)
    sample = next(row for row in result if row["tool"] == "aws")
    for key in (
        "label", "category", "summary", "includes", "excludes",
        "default_enabled", "config_kind", "since",
    ):
        assert key in sample, f"missing meta key in MCP payload: {key}"
    assert sample["label"] == "AWS CLI"


def test_dispatch_unknown_tool_raises() -> None:
    from anvyc.mcp.server import _dispatch

    with pytest.raises(ValueError, match="unknown tool"):
        _dispatch("anvyc_invalid", {})


def test_tool_defs_advertises_9_tools() -> None:
    # PR #33 (CP-1 3/3) 에서 activity_summary + tool_call_stats 가 추가되어 5 → 7.
    # PR-13B1 (CP-13) 에서 cost_summary 추가로 7 → 8.
    # CP-14 Phase 3 에서 run_summary 추가로 8 → 9 (L4 실행 엔진 원장 흡수).
    from anvyc.mcp.server import _tool_defs

    defs = _tool_defs()
    assert len(defs) == 9
    names = {t.name for t in defs}
    assert names == {
        "project_show",
        "project_list",
        "project_doctor",
        "doctor",
        "tools_list",
        "activity_summary",
        "tool_call_stats",
        "cost_summary",
        "run_summary",
    }
