"""tests/unit/test_mcp_extra_importable_check.py — doctor mcp-extra-importable.

`anvyc serve --mcp` 가 동작하려면 `mcp` 패키지 (anvyc[mcp] extra) 가 venv 에
설치돼 있어야 한다. 미설치 시 silent failure 가 일어나는 경로를 doctor 가
WARNING 으로 잡도록 한다.
"""
from __future__ import annotations

import sys

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.mcp_extra_importable import McpExtraImportableCheck


def test_mcp_present_returns_empty() -> None:
    """현재 dev 환경은 anvyc[mcp] 가 설치되어 있으므로 빈 결과."""
    results = McpExtraImportableCheck().run(CheckContext())
    assert results == []


def test_mcp_absent_emits_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """sys.modules 에 mcp=None 을 주입해 importlib.util.find_spec 실패를 강제."""
    monkeypatch.setitem(sys.modules, "mcp", None)
    results = McpExtraImportableCheck().run(CheckContext())
    assert len(results) == 1
    r = results[0]
    assert r.check_name == "mcp-extra-importable"
    assert r.severity == Severity.WARNING
    assert "mcp" in r.message.lower()
    assert r.suggestion is not None
    # 설치 명령이 사용자에게 정확히 노출 — PR #71 에서 fix 한 [mcp] 누락 회귀와 같은
    # 정확성 보장
    assert "anvyc[mcp]" in r.suggestion
