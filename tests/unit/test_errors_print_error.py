"""tests/unit/test_errors_print_error.py — safe_msg / print_error 회귀.

`console.print(f"... {variable}")` 패턴에서 variable 의 `[xxx]` 표기가 Rich
markup parser 에 silent strip 되는 버그(PR #71) 의 재발을 막는다. 이 helper
는 외부 값(예외·subprocess 출력·diff 라인)을 출력할 때 항상 경유해야 한다.
"""
from __future__ import annotations

import io

from rich.console import Console

from anvyc.utils.errors import print_error, safe_msg


def _make_console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, force_terminal=False, no_color=True, width=200), buf


def test_safe_msg_preserves_brackets() -> None:
    assert safe_msg("install 'anvyc[mcp]'") == "install 'anvyc\\[mcp]'"
    # int / Path-like 도 str 으로 변환 후 escape
    assert safe_msg(42) == "42"


def test_print_error_preserves_bracket_notation() -> None:
    """[mcp] 표기가 출력에서 strip 되지 않아야 한다 (PR #71 회귀 방지)."""
    c, buf = _make_console()
    print_error("requires the [mcp] extra. Install: pip install 'anvyc[mcp]'", console=c)
    out = buf.getvalue().rstrip()
    assert "error" in out
    assert "[mcp] extra" in out, f"missing '[mcp] extra' in: {out!r}"
    assert "'anvyc[mcp]'" in out, f"missing \"'anvyc[mcp]'\" in: {out!r}"


def test_print_error_accepts_exception_object() -> None:
    """예외 객체를 그대로 넘겨도 str() 변환 후 escape 된다."""
    c, buf = _make_console()
    print_error(ValueError("got [DROP] command"), console=c)
    out = buf.getvalue().rstrip()
    assert "got [DROP] command" in out
