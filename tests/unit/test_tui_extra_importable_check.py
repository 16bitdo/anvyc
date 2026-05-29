"""tests/unit/test_tui_extra_importable_check.py — doctor tui-extra-importable.

textual([tui] extra) 미설치는 *실패가 아니라* configure 의 기능 강등(번호 메뉴)이므로
이 check 는 INFO 다. 설치돼 있으면 빈 결과, 없으면 설치 경로 안내 1건.
"""
from __future__ import annotations

import sys

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.tui_extra import TuiExtraImportableCheck


def test_textual_present_returns_empty() -> None:
    """dev/CI 환경은 anvyc[tui] 설치 → 빈 결과."""
    assert TuiExtraImportableCheck().run(CheckContext()) == []


def test_textual_absent_emits_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """sys.modules 에 textual=None 주입 → find_spec 가 None → INFO 1건."""
    monkeypatch.setitem(sys.modules, "textual", None)
    results = TuiExtraImportableCheck().run(CheckContext())
    assert len(results) == 1
    r = results[0]
    assert r.check_name == "tui-extra-importable"
    assert r.severity == Severity.INFO  # WARNING 아님 — 강등이지 실패 아님
    assert r.suggestion is not None
    assert "anvyc[tui]" in r.suggestion


def test_check_registered_in_doctor() -> None:
    """doctor registry 에 등록되어 run_doctor 에서 실행되는지."""
    from anvyc.core.doctor import _REGISTRY

    assert "tui-extra-importable" in _REGISTRY
