"""claude-md-freshness doctor check 단위테스트."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from anvyc.checks import claude_md_freshness as mod
from anvyc.checks.base import CheckContext, Severity


def _ctx() -> CheckContext:
    return CheckContext()


def test_skip_when_rbr_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_rbr_script", lambda: Path("/no/such/rbr/generate_claude_md.py"))
    assert mod.ClaudeMdFreshnessCheck().run(_ctx()) == []


def test_fresh_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "generate_claude_md.py"
    script.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(mod, "_rbr_script", lambda: script)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, "[check] OK", ""))
    assert mod.ClaudeMdFreshnessCheck().run(_ctx()) == []


def test_stale_returns_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "generate_claude_md.py"
    script.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(mod, "_rbr_script", lambda: script)
    out = "[check] 2 stale generated CLAUDE.md (8 checked):\n  - anvyc: /x/CLAUDE.md  — ...\n  - ctxport: /y/CLAUDE.md  — ...\n"
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, out, ""))
    results = mod.ClaudeMdFreshnessCheck().run(_ctx())
    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert "stale" in results[0].message
