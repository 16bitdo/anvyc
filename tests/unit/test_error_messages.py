"""Standardized error message (English) — print_blocked_error helper.

Capture Rich Console output via record=True and verify the standard format.
"""
from __future__ import annotations

from rich.console import Console

from anvyc.core.apply import ApplyBlocked
from anvyc.core.backup import BackupBlocked
from anvyc.utils.errors import print_blocked_error


def _record() -> Console:
    return Console(record=True, width=200, force_terminal=False)


def test_blocked_error_default_format_english() -> None:
    """Standard message ships English title + bullet reasons."""
    c = _record()
    print_blocked_error(
        "backup",
        ["a critical secret was found", "a high-severity finding remains"],
        next_steps=["anvyc doctor", "anvyc scan-secrets <path>"],
        allow_force=True,
        console=c,
    )
    text = c.export_text()
    assert "backup blocked" in text
    assert "secret scan" in text  # English
    assert "• a critical secret was found" in text
    assert "• a high-severity finding remains" in text
    assert "Next steps:" in text
    assert "- anvyc doctor" in text
    assert "- anvyc scan-secrets <path>" in text
    assert "--force allowed" in text
    # Korean should not appear in standardized blocks
    assert "중단" not in text
    assert "차단" not in text


def test_blocked_error_no_force_omits_force_line() -> None:
    """allow_force=False suppresses the --force hint line."""
    c = _record()
    print_blocked_error(
        "apply",
        ["irreversible: critical secret in source"],
        next_steps=["anvyc doctor"],
        allow_force=False,
        console=c,
    )
    text = c.export_text()
    assert "apply blocked" in text
    assert "--force allowed" not in text


def test_blocked_error_empty_reasons_yields_unknown_cause() -> None:
    """Empty reasons list produces a fallback message."""
    c = _record()
    print_blocked_error("restore", [], next_steps=None, console=c)
    text = c.export_text()
    assert "restore blocked: cause unknown" in text
    assert "Next steps:" not in text


def test_blocked_error_no_next_steps_omits_section() -> None:
    """next_steps=None hides the 'Next steps:' header."""
    c = _record()
    print_blocked_error("backup", ["reason A"], next_steps=None, console=c)
    text = c.export_text()
    assert "Next steps:" not in text
    assert "• reason A" in text


def test_backup_blocked_carries_default_next_steps() -> None:
    """BackupBlocked default next_steps include doctor + scan-secrets."""
    exc = BackupBlocked(["a"])
    assert exc.allow_force is True
    assert any("doctor" in s for s in exc.next_steps)
    assert any("scan-secrets" in s for s in exc.next_steps)


def test_apply_blocked_carries_default_next_steps() -> None:
    """ApplyBlocked default next_steps include doctor + diff."""
    exc = ApplyBlocked(["b"])
    assert exc.allow_force is True
    assert any("doctor" in s for s in exc.next_steps)
    assert any("diff" in s for s in exc.next_steps)
