"""CLI --help 출력의 panel 그룹 검증 (PR C — v0.16.0).

환경 견고성: CI 러너가 색을 강제(FORCE_COLOR)하면 Rich 가 ANSI escape 로 박스 문자
(`│`)·옵션명을 감싸고, 좁은 폭에선 긴 옵션명이 줄바꿈돼 raw substring 매칭이 깨진다.
`_help_out()` 이 (1) 넓은 폭 고정(COLUMNS) 으로 줄바꿈을, (2) ANSI 제거로 색코드를
흡수한다 → 테스트는 렌더 색/폭과 무관하게 '내용'만 검증한다.
"""

from __future__ import annotations

import re

from typer.testing import CliRunner

from anvyc.cli import app

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _help_out() -> str:
    """`anvyc --help` 출력을 넓은 폭 + ANSI 제거로 정규화해 반환 (exit 0 보장)."""
    result = CliRunner().invoke(app, ["--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    return _ANSI_RE.sub("", result.stdout)


def test_help_renders_all_five_panels() -> None:
    """`anvyc --help` 의 5 panel 헤더가 모두 노출."""
    out = _help_out()
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
    out = _help_out()
    for token in ("CP-4,", "CP-5,", "CP-6,", "CP-12 PR", "CP-13 PR", "v2 진입", "v3"):
        assert token not in out, f"raw ADR marker '{token}' leaked into top-level --help"


def test_completion_options_exposed() -> None:
    """`add_completion=True` (default) → `--install-completion` / `--show-completion` 노출."""
    out = _help_out()
    assert "--install-completion" in out
    assert "--show-completion" in out


def test_mcp_command_in_mcp_panel() -> None:
    """`mcp` group 이 MCP / serve panel 안에 위치 (header 가 mcp 라인보다 앞)."""
    out = _help_out()
    mcp_panel_idx = out.find("MCP / serve")
    # 박스 라인 `│ mcp ...` — 색/폭 정규화 후 매칭 (선행 공백 허용).
    mcp_line = re.search(r"│\s+mcp\b", out)
    assert mcp_panel_idx >= 0, "MCP / serve panel header 부재"
    assert mcp_line is not None, "`mcp` 명령 라인 부재"
    assert mcp_panel_idx < mcp_line.start(), "mcp 라인이 panel header 보다 앞에 위치"


def test_control_plane_panel_includes_axes() -> None:
    """Control plane panel 에 6 axis 명령이 모두 포함."""
    out = _help_out()
    panel_start = out.find("Control plane")
    assert panel_start >= 0
    panel_body = out[panel_start:]
    cut = panel_body.find("External tools")
    if cut >= 0:
        panel_body = panel_body[:cut]
    for cmd in ("activity", "snapshot", "creds", "sync", "workctx", "cost"):
        assert cmd in panel_body, f"`{cmd}` not in Control plane panel body"
