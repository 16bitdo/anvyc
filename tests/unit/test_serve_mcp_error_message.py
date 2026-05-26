"""tests/unit/test_serve_mcp_error_message.py — regression for Rich markup strip.

`anvyc serve --mcp` 호출 시 `mcp` extra 미설치 상태이면 cli.py 의 except 절이
SystemExit 메시지를 `console.print` 로 표시한다. Rich console 은 `[mcp]` 같은
대괄호를 markup 으로 파싱해 silent strip 했기 때문에, pip extra 표기가 사라져
사용자에게 잘못된 설치 명령(`pip install 'anvyc'`)을 안내하는 버그가 있었다.

본 테스트는 fix (`rich.markup.escape`) 가 제거되지 않도록 회귀를 막는다.
"""
from __future__ import annotations

import sys

import pytest
from typer.testing import CliRunner

from anvyc.cli import app


def test_serve_mcp_missing_extra_preserves_bracket_notation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mcp 패키지 미설치 시 출력에 '[mcp]' 와 "'anvyc[mcp]'" 가 그대로 노출돼야 한다."""
    # upstream `mcp` 패키지를 import 불가 상태로 만들어 anvyc.mcp.server 의
    # SystemExit 경로를 강제로 탄다.
    for mod in ("mcp", "mcp.server", "mcp.server.stdio", "mcp.types"):
        monkeypatch.setitem(sys.modules, mod, None)
    # 이미 import 된 anvyc.mcp.server 캐시를 비워 재-import 가 SystemExit 던지도록.
    monkeypatch.delitem(sys.modules, "anvyc.mcp.server", raising=False)

    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--mcp"])

    assert result.exit_code == 1
    # Rich markup strip 회귀 방지 — 대괄호 표기가 그대로 보존돼야 한다.
    assert "[mcp] extra" in result.output, f"missing '[mcp] extra' in: {result.output!r}"
    assert "'anvyc[mcp]'" in result.output, f"missing \"'anvyc[mcp]'\" in: {result.output!r}"
