"""Standardized CLI error message helpers (v0.6.3).

All user-facing error output from blocked operations (BackupBlocked, ApplyBlocked,
etc.) flows through `print_blocked_error()` to produce a consistent format:

    <action> blocked: <cause>
      • reason 1
      • reason 2
    Next steps:
      - <command 1>
      - <command 2>
      - (--force allowed for medium-severity findings)

English by user policy (v0.6.3 — W3.4 / E6).
"""
from __future__ import annotations

from rich.console import Console

_default_console: Console | None = None


def _get_console() -> Console:
    global _default_console
    if _default_console is None:
        _default_console = Console()
    return _default_console


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
