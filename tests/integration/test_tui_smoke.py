"""Textual TUI 뷰 스모크 (PR4) — Pilot 헤드리스 구동.

textual 미설치 환경에서는 skip. 토글 메커니즘(focus 의존)이 아니라 save→맵 /
cancel→None 의 계약만 검증해 버전·focus 변화에 견고하게 한다.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from anvyc.core.tools_select import ToolChoice  # noqa: E402
from anvyc.ui.tui import ToolsConfigureApp  # noqa: E402


def _choices() -> list[ToolChoice]:
    return [
        ToolChoice("shell", "Shell", "shell", "zsh", True, False, True),
        ToolChoice("git", "Git", "vcs", "git cfg", False, True, True),
    ]


async def _run(keys: list[str]) -> dict[str, bool] | None:
    app = ToolsConfigureApp(_choices())
    async with app.run_test() as pilot:
        for k in keys:
            await pilot.press(k)
    return app.return_value


def test_tui_save_returns_full_map() -> None:
    """s 저장 → 모든 도구의 현재 상태 맵 반환 (토글 없이 초기값 그대로)."""
    result = asyncio.run(_run(["s"]))
    assert result == {"shell": True, "git": False}


def test_tui_cancel_returns_none() -> None:
    """q 취소 → None."""
    assert asyncio.run(_run(["q"])) is None
