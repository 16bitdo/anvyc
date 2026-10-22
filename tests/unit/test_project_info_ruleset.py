"""project_show 의 `ruleset` 블록 — 프로젝트가 어느 룰셋(role·commit)에 있고 신선한지.

2026-10-22 role-based-ruleset 리뷰 항목 4: 에이전트가 프로젝트 단위로 "내 룰셋 버전·신선도" 를 물을
수단이 CLAUDE.md 헤더 파싱밖에 없었다(claude-md-freshness 는 global doctor 에서 fleet 전체를 한 문자열로).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from anvyc.core import project_info as mod

_HEADER = (
    "<!-- auto-generated from .cursor/rules/ by generate_claude_md.py — do not edit manually -->\n"
    "<!-- role: devops-engineer | source: .cursor/rules/ | generated_at: 2026-10-23T07:47:00+09:00"
    " | ruleset_version: v1.0.0-437-g6b32986 | ruleset_commit: 6b32986 -->\n\n## body\n"
)


def _project(tmp_path: Path, *, generated: bool = True, rules: int = 3) -> Path:
    p = tmp_path / "proj"
    (p / ".cursor" / "rules").mkdir(parents=True)
    for i in range(rules):
        (p / ".cursor" / "rules" / f"{i:02d}-r.mdc").write_text("---\n---\nb\n")
    (p / "CLAUDE.md").write_text(_HEADER if generated else "# 손으로 쓴 CLAUDE.md\n")
    return p


def test_ruleset_block_parsed_from_generated_header(tmp_path: Path) -> None:
    info = mod.collect_project_info(_project(tmp_path))
    assert info.ruleset == {
        "role": "devops-engineer",
        "generated_at": "2026-10-23T07:47:00+09:00",
        "ruleset_version": "v1.0.0-437-g6b32986",
        "ruleset_commit": "6b32986",
        "cursor_rules": 3,
    }
    assert mod.to_dict(info)["ruleset"]["ruleset_commit"] == "6b32986"


def test_ruleset_none_for_manual_or_missing_claude_md(tmp_path: Path) -> None:
    assert mod.collect_project_info(_project(tmp_path, generated=False)).ruleset is None
    bare = tmp_path / "bare"
    bare.mkdir()
    assert mod.collect_project_info(bare).ruleset is None


def test_ruleset_freshness_uses_rbr_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _project(tmp_path)
    script = tmp_path / "generate_claude_md.py"
    script.write_text("# stub")
    monkeypatch.setattr(mod, "_rbr_generate_script", lambda: script)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    assert mod.ruleset_freshness(p) is True
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
    assert mod.ruleset_freshness(p) is False


def test_ruleset_freshness_unknown_when_rbr_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "_rbr_generate_script", lambda: Path("/no/such/generate_claude_md.py"))
    assert mod.ruleset_freshness(_project(tmp_path)) is None
    # 생성물이 아니면 묻지 않는다
    assert mod.ruleset_freshness(_project(tmp_path / "x", generated=False)) is None
