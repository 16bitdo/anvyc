"""CLI --help 출력의 panel 그룹 검증 (PR C — v0.16.0)."""

from __future__ import annotations

from typer.testing import CliRunner

from anvyc.cli import app


def test_help_renders_all_five_panels() -> None:
    """`anvyc --help` 의 5 panel 헤더가 모두 노출."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0

    # 5 panel header (테두리 char 제외, panel 이름만 substring 검증)
    out = result.stdout
    assert "Core (backup/apply/restore)" in out
    assert "Project view" in out
    assert "Control plane" in out
    assert "MCP / serve" in out
    assert "External tools" in out


def test_help_has_no_adr_marker_in_first_screen() -> None:
    """top-level --help 1차 표면에서는 ADR marker (CP-12 PR-12E 등) 노출 안 함.

    docstring 본문 (sub-command 의 --help) 에는 검색용 keyword 가 남을 수 있으나
    `anvyc --help` 첫 화면에서는 사용자에게 의미 없는 ADR 코드를 제거 (v0.16.0).
    """
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    out = result.stdout

    # 사용자에게 의미 없는 raw ADR marker
    for token in ("CP-4,", "CP-5,", "CP-6,", "CP-12 PR", "CP-13 PR", "v2 진입", "v3"):
        assert token not in out, f"raw ADR marker '{token}' leaked into top-level --help"


def test_completion_options_exposed() -> None:
    """`add_completion=True` (default) → `--install-completion` / `--show-completion` 노출."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--install-completion" in result.stdout
    assert "--show-completion" in result.stdout


def test_mcp_command_in_mcp_panel() -> None:
    """`mcp` group 이 MCP / serve panel 안에 위치."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    out = result.stdout
    # panel header 와 mcp 명령 라인의 순서 — header 가 먼저, 이후 mcp.
    mcp_panel_idx = out.find("MCP / serve")
    mcp_line_idx = out.find("\n│ mcp ")
    assert mcp_panel_idx >= 0 and mcp_line_idx >= 0
    # mcp 라인이 MCP / serve panel header 의 뒤에 위치해야 함
    assert mcp_panel_idx < mcp_line_idx


def test_control_plane_panel_includes_axes() -> None:
    """Control plane panel 에 6 axis 명령이 모두 포함."""
    result = CliRunner().invoke(app, ["--help"])
    out = result.stdout
    panel_start = out.find("Control plane")
    assert panel_start >= 0
    # 본 panel 직후 (다른 panel 시작 전) 본문에서 axes 명령 검출
    panel_body = out[panel_start:]
    # External tools panel 직전까지 자르기
    cut = panel_body.find("External tools")
    if cut >= 0:
        panel_body = panel_body[:cut]
    for cmd in ("activity", "snapshot", "creds", "sync", "workctx", "cost"):
        assert cmd in panel_body, f"`{cmd}` not in Control plane panel body"
