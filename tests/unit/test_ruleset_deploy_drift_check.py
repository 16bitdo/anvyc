"""tests/unit/test_ruleset_deploy_drift_check.py — L2 ruleset-deploy-drift check.

검증 항목:
1. 비-git / ref 부재 (behind_count=None) → 빈 results (무오탐 skip)
2. 최신 (behind_count=0) → WARNING 없음
3. 뒤처짐 (behind_count>0) → WARNING + 커밋 수 + pull suggestion
4. behind_count: 실제 비-git tmp dir → None
"""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.checks import ruleset_deploy_drift as mod
from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.ruleset_deploy_drift import RulesetDeployDriftCheck


def test_not_applicable_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "behind_count", lambda _repo: None)
    assert RulesetDeployDriftCheck().run(CheckContext()) == []


def test_up_to_date_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "behind_count", lambda _repo: 0)
    assert RulesetDeployDriftCheck().run(CheckContext()) == []


def test_behind_warns_with_count_and_suggestion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "behind_count", lambda _repo: 3)
    results = RulesetDeployDriftCheck().run(CheckContext())
    assert len(results) == 1
    r = results[0]
    assert r.severity == Severity.WARNING
    assert "3" in r.message
    assert r.suggestion is not None
    assert "pull" in r.suggestion


def test_behind_count_non_git_returns_none(tmp_path: Path) -> None:
    assert mod.behind_count(tmp_path) is None
