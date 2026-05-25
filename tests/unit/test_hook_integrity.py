"""tests/unit/test_hook_integrity.py — CP-8 PR-B hook integrity check.

검증 항목:
1. ~/.claude* 부재 → 빈 results (비대상)
2. settings.json 부재 → 해당 프로필 skip
3. 모든 hook 3종 wire → WARNING 없음
4. 일부 hook 누락 → WARNING (누락 목록 포함)
5. hooks.PreToolUse 없음 → 3개 모두 missing → WARNING
6. settings.json JSON 손상 → WARNING (parse 실패 메시지)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.hook_integrity import (
    RISK_GATE_HOOK_NAMES,
    HookIntegrityRiskGateCheck,
    discover_claude_settings,
    wired_risk_gate_hooks,
)


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Path.home() 를 tmp_path 로 patch."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def _write_settings(claude_dir: Path, hooks: dict[str, object]) -> Path:
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings = claude_dir / "settings.json"
    settings.write_text(json.dumps({"hooks": hooks}, indent=2), encoding="utf-8")
    return settings


def _full_wire() -> dict[str, object]:
    """3개 risk-gate hook 모두 wire 된 hooks dict."""
    return {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    {"type": "command", "command": f"/x/{name}.sh"}
                    for name in RISK_GATE_HOOK_NAMES
                ],
            }
        ]
    }


def test_no_claude_dirs_returns_empty(fake_home: Path) -> None:
    check = HookIntegrityRiskGateCheck()
    assert check.run(CheckContext()) == []


def test_full_wire_no_warning(fake_home: Path) -> None:
    _write_settings(fake_home / ".claude", _full_wire())
    _write_settings(fake_home / ".claude-edward", _full_wire())
    check = HookIntegrityRiskGateCheck()
    assert check.run(CheckContext()) == []


def test_partial_wire_warns_with_missing(fake_home: Path) -> None:
    _write_settings(
        fake_home / ".claude",
        {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "/x/destructive-keyword-block.sh"},
                    ],
                }
            ]
        },
    )
    results = HookIntegrityRiskGateCheck().run(CheckContext())
    assert len(results) == 1
    r = results[0]
    assert r.severity == Severity.WARNING
    assert "aws-prod-account-confirm" in r.message
    assert "account-routing-mismatch" in r.message
    assert r.suggestion is not None
    assert "ccinspector" in r.suggestion


def test_missing_pretooluse_warns_all(fake_home: Path) -> None:
    _write_settings(fake_home / ".claude", {})
    results = HookIntegrityRiskGateCheck().run(CheckContext())
    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    # 3/3 missing
    assert "3/3" in results[0].message


def test_corrupted_json_warns(fake_home: Path) -> None:
    claude = fake_home / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{not valid json", encoding="utf-8")
    results = HookIntegrityRiskGateCheck().run(CheckContext())
    assert len(results) == 1
    assert "파싱 실패" in results[0].message


def test_discover_claude_settings_includes_multi_profile(fake_home: Path) -> None:
    _write_settings(fake_home / ".claude", _full_wire())
    _write_settings(fake_home / ".claude-edward", _full_wire())
    _write_settings(fake_home / ".claude-jklee", _full_wire())
    # 비-claude 디렉토리는 무시
    (fake_home / ".cursor").mkdir()
    (fake_home / ".cursor" / "settings.json").write_text("{}", encoding="utf-8")

    found = discover_claude_settings()
    names = {p.parent.name for p in found}
    assert names == {".claude", ".claude-edward", ".claude-jklee"}


def test_wired_helper_handles_malformed_inputs() -> None:
    assert wired_risk_gate_hooks({}) == set()
    assert wired_risk_gate_hooks({"hooks": "wrong-type"}) == set()
    assert wired_risk_gate_hooks({"hooks": {"PreToolUse": "wrong"}}) == set()
    assert wired_risk_gate_hooks({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": "wrong"}]}}) == set()
    # command 가 dict 아닌 string 등
    assert wired_risk_gate_hooks(
        {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": ["string-not-dict"]}]}}
    ) == set()


def test_wired_helper_detects_partial_match() -> None:
    """deploy path prefix 가 달라도 hook 이름이 command 에 포함되면 wire 로 판정."""
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "/any/long/path/destructive-keyword-block.sh extra-args"},
                        {"type": "command", "command": "~/.cci/hooks/account-routing-mismatch.sh"},
                    ],
                }
            ]
        }
    }
    assert wired_risk_gate_hooks(settings) == {
        "destructive-keyword-block",
        "account-routing-mismatch",
    }
