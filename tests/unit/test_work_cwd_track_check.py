"""tests/unit/test_work_cwd_track_check.py — CP-12 PR-12F doctor check 회귀."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.work_cwd_track import WorkCwdTrackWiredCheck


def _make_profile(tmp_path: Path, profile: str, settings_data: dict[str, Any]) -> Path:
    """Create ~/.<profile>/settings.json under tmp_path as fake home."""
    home = tmp_path / "home"
    pdir = home / f".{profile}"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "settings.json").write_text(json.dumps(settings_data), encoding="utf-8")
    return home


def _settings_phase_a_only() -> dict[str, Any]:
    return {
        "hooks": {
            "CwdChanged": [
                {"hooks": [{"type": "command", "command": "/path/to/work-cwd-track.sh"}]}
            ],
        },
        "env": {"WORK_CWD_CACHE": "/some/path"},
    }


def _settings_phase_a_b() -> dict[str, Any]:
    return {
        "hooks": {
            "CwdChanged": [
                {"hooks": [{"type": "command", "command": "/path/to/cwd-changed/work-cwd-track.sh"}]}
            ],
            "PostToolUse": [
                {
                    "matcher": "Read|Write|Edit|MultiEdit",
                    "hooks": [{"type": "command", "command": "/path/to/post-tool-use/work-cwd-track.sh"}],
                }
            ],
        },
        "env": {"WORK_CWD_CACHE": "/Users/x/.claude-edward/.work-cwd-cache"},
    }


def _settings_other_hooks_only() -> dict[str, Any]:
    """Hook 다른 종류만 있고 work-cwd-track 부재."""
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "/path/destructive-keyword-block.sh"}],
                }
            ]
        }
    }


def test_no_profiles_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """홈에 .claude* 프로필 없으면 빈 결과."""
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: empty_home)
    results = WorkCwdTrackWiredCheck().run(CheckContext())
    assert results == []


def test_fully_wired_phase_ab_no_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _make_profile(tmp_path, "claude-edward", _settings_phase_a_b())
    monkeypatch.setattr(Path, "home", lambda: home)
    results = WorkCwdTrackWiredCheck().run(CheckContext())
    assert results == [], f"unexpected results: {results}"


def test_phase_a_only_warns_phase_b_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _make_profile(tmp_path, "claude-edward", _settings_phase_a_only())
    monkeypatch.setattr(Path, "home", lambda: home)
    results = WorkCwdTrackWiredCheck().run(CheckContext())
    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert "Phase B" in results[0].message
    assert "Phase A" not in results[0].message  # Phase A 는 wired
    assert "WORK_CWD_CACHE" not in results[0].message


def test_no_hooks_and_no_env_warns_all_three(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _make_profile(tmp_path, "claude-edward", _settings_other_hooks_only())
    monkeypatch.setattr(Path, "home", lambda: home)
    results = WorkCwdTrackWiredCheck().run(CheckContext())
    assert len(results) == 1
    msg = results[0].message
    assert "Phase A" in msg
    assert "Phase B" in msg
    assert "WORK_CWD_CACHE" in msg
    assert "3 항목" in msg


def test_env_only_no_hooks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _make_profile(
        tmp_path,
        "claude",
        {"env": {"WORK_CWD_CACHE": "/path/to/cache"}},
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    results = WorkCwdTrackWiredCheck().run(CheckContext())
    assert len(results) == 1
    msg = results[0].message
    assert "Phase A" in msg
    assert "Phase B" in msg
    assert "WORK_CWD_CACHE" not in msg


def test_multiple_profiles_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile fully wired, B profile partial → B 만 warning."""
    home = tmp_path / "home"
    ok_dir = home / ".claude-ok"
    ok_dir.mkdir(parents=True)
    (ok_dir / "settings.json").write_text(json.dumps(_settings_phase_a_b()), encoding="utf-8")
    bad_dir = home / ".claude-bad"
    bad_dir.mkdir(parents=True)
    (bad_dir / "settings.json").write_text(json.dumps(_settings_phase_a_only()), encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: home)
    results = WorkCwdTrackWiredCheck().run(CheckContext())
    assert len(results) == 1
    assert "claude-bad" in str(results[0].location)
    assert "Phase B" in results[0].message


def test_malformed_settings_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    pdir = home / ".claude"
    pdir.mkdir(parents=True)
    (pdir / "settings.json").write_text("not-valid-json{[", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: home)
    results = WorkCwdTrackWiredCheck().run(CheckContext())
    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert "파싱 실패" in results[0].message


def test_phase_b_only_missing_phase_a_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase B 만 배선 + env 누락 → 2 항목 missing."""
    home = _make_profile(
        tmp_path,
        "claude",
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Read|Write|Edit|MultiEdit",
                        "hooks": [{"type": "command", "command": "/path/work-cwd-track.sh"}],
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    results = WorkCwdTrackWiredCheck().run(CheckContext())
    assert len(results) == 1
    msg = results[0].message
    assert "Phase A" in msg
    assert "Phase B" not in msg
    assert "WORK_CWD_CACHE" in msg
    assert "2 항목" in msg
