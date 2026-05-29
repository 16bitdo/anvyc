"""Textual 체크박스 TUI — `anvyc tools configure` 의 선택 화면 (PR4).

thin view: 토글 가능한 체크박스 목록만 그리고, 선택 결과(name→enabled)만 반환한다.
diff 미리보기·확인·yaml 쓰기 등 로직은 cli + core.tools_select 가 그대로 담당한다.

이 모듈은 `textual` (선택 extra `[tui]`) 이 설치된 경우에만 import 된다 — cli 는
호출 전 `importlib.util.find_spec("textual")` 로 가용성을 확인하고, 없으면 번호 토글
메뉴로 폴백한다. 따라서 여기서는 textual 을 module-level 로 import 해도 안전하다.
"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Checkbox, Footer, Header

from anvyc.core.tools_select import ToolChoice


def _label(choice: ToolChoice) -> str:
    det = "detected" if choice.detected else "not-detected"
    return f"{choice.name}  ·  {choice.category}  ·  [{det}]  {choice.summary}"


class ToolsConfigureApp(App[dict[str, bool]]):
    """도구 enabled 토글 체크박스 — space 토글 · s 저장 · q/esc 취소.

    `run()` (또는 `run_test()`) 의 반환값은 저장 시 name→enabled 맵, 취소 시 None.
    """

    TITLE = "anvyc tools configure"
    SUB_TITLE = "space 토글 · s 저장 · q/esc 취소"
    BINDINGS = [
        Binding("s", "save", "저장"),
        Binding("q", "cancel", "취소"),
        Binding("escape", "cancel", "취소"),
    ]

    def __init__(self, choices: list[ToolChoice]) -> None:
        super().__init__()
        self._choices = choices

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            for c in self._choices:
                yield Checkbox(_label(c), value=c.enabled, id=f"tool-{c.name}")
        yield Footer()

    def action_save(self) -> None:
        result = {
            c.name: bool(self.query_one(f"#tool-{c.name}", Checkbox).value)
            for c in self._choices
        }
        self.exit(result)

    def action_cancel(self) -> None:
        self.exit(None)


def run_tui_selection(choices: list[ToolChoice]) -> dict[str, bool] | None:
    """체크박스 TUI 를 띄워 name→enabled 선택을 받는다. 취소 시 None."""
    return ToolsConfigureApp(choices).run()
