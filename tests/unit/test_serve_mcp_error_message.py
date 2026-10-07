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

import anvyc
from anvyc.cli import app
from anvyc.core import install_method as im
from anvyc.core.extras import install_hint
from anvyc.core.install_method import InstallContext


def test_serve_mcp_missing_extra_prints_install_command_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mcp 미설치 시 '[mcp] extra' 와 설치 명령 전문이 그대로(대괄호·한 줄) 나와야 한다."""
    for mod in ("mcp", "mcp.server", "mcp.server.stdio", "mcp.types"):
        monkeypatch.setitem(sys.modules, mod, None)
    monkeypatch.delitem(sys.modules, "anvyc.mcp.server", raising=False)
    # 대괄호가 든 안내(venv 형)로 고정 — Rich markup strip 회귀(PR #71)를 계속 잡는다.
    monkeypatch.setattr(im, "detect", lambda: InstallContext("venv", "/v/bin/python"))
    monkeypatch.setattr(anvyc, "__version__", "0.23.0")
    hint = install_hint("mcp")
    assert "'anvyc[" in hint and " @ https://" in hint

    result = CliRunner().invoke(app, ["serve", "--mcp"])

    assert result.exit_code == 1
    assert "[mcp] extra" in result.output, f"missing '[mcp] extra' in: {result.output!r}"
    assert hint in result.output, f"missing install command in: {result.output!r}"
