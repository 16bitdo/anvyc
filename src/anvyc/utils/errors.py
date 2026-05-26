"""Standardized CLI error message helpers (v0.6.3).

All user-facing error output from blocked operations (BackupBlockedError, ApplyBlockedError,
etc.) flows through `print_blocked_error()` to produce a consistent format:

    <action> blocked: <cause>
      • reason 1
      • reason 2
    Next steps:
      - <command 1>
      - <command 2>
      - (--force allowed for medium-severity findings)

English by user policy (v0.6.3 — W3.4 / E6).

또한 `print_error()` / `safe_msg()` 는 Rich console 의 markup parser 가 외부
값(예외 메시지·경로)에 등장한 `[xxx]` 표기를 silent strip 하지 않도록 escape
한 뒤 출력하는 표준 헬퍼다. 직접 `console.print(f"[red]error[/] {e}")` 형태를
쓰지 말고 이 헬퍼를 경유할 것 (PR #71 회귀 방지).
"""
from __future__ import annotations

from rich.console import Console
from rich.markup import escape

_default_console: Console | None = None


def _get_console() -> Console:
    global _default_console
    if _default_console is None:
        _default_console = Console()
    return _default_console


def safe_msg(value: object) -> str:
    """Rich markup 으로 오해될 수 있는 `[xxx]` 표기를 escape 한 str.

    예외 메시지·경로·외부 명령 출력처럼 brace 가 포함될 가능성이 있는 값을
    `console.print` 의 f-string 안에 끼울 때 사용한다.
    """
    return escape(str(value))


def print_error(message: object, *, console: Console | None = None) -> None:
    """`[red]error[/] <escaped message>` 형식으로 출력.

    `message` 본문은 항상 Rich escape — 외부 값에 우연히 들어 있는 `[mcp]`
    같은 표기가 markup parser 에 strip 되는 사고를 차단한다.
    """
    c = console or _get_console()
    c.print(f"[red]error[/] {safe_msg(message)}")


def print_blocked_error(
    action: str,
    reasons: list[str],
    *,
    next_steps: list[str] | None = None,
    allow_force: bool = False,
    console: Console | None = None,
) -> None:
    """Print a standard 'blocked' error message in English.

    Parameters
    ----------
    action:
        verb of the blocked operation ("backup", "apply", "restore", "scan").
    reasons:
        list of cause descriptions surfaced from the exception.
    next_steps:
        optional remediation commands shown after reasons. Falsy → omitted.
    allow_force:
        if true, adds a "--force allowed (medium severity only)" line.
    console:
        injection point for tests; defaults to module-level Rich Console.
    """
    c = console or _get_console()
    if not reasons:
        c.print(f"[red bold]{action} blocked: cause unknown[/]")
    else:
        c.print(f"[red bold]{action} blocked: secret scan rejected the operation[/]")
        for r in reasons:
            c.print(f"  • {r}")

    if next_steps:
        c.print("[bold]Next steps:[/]")
        for s in next_steps:
            c.print(f"  - {s}")

    if allow_force:
        c.print(
            "[dim]  - --force allowed for medium-severity findings "
            "(critical/high cannot be forced)[/]"
        )
