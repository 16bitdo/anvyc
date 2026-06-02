# tests/unit/test_project_branch_protection.py
"""Unit tests for project-branch-protection check."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.project_branch_protection import ProjectBranchProtectionCheck
from anvyc.core.branch_policy import BranchPolicy

_PROTECTED = BranchPolicy(
    default_branch="main", protected_branches=("main",), push_to_main_allowed=False,
    pr_required=True, pr_reviewers_min=0, merge_strategy="squash", source="manifest",
)
_ALLOWED = BranchPolicy(
    default_branch="main", protected_branches=("main",), push_to_main_allowed=True,
    pr_required=False, pr_reviewers_min=0, merge_strategy="squash", source="manifest",
)


@pytest.fixture
def one_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / ".git" / "hooks").mkdir(parents=True)
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.resolve_guard_targets",
        lambda project, root: [repo],
    )
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.origin_owner_repo",
        lambda d: ("16bitdo", "proj"),
    )
    return repo


def test_aligned_yields_info(one_repo: Path) -> None:
    (one_repo / ".git" / "hooks" / "pre-push").write_text("# >>> anvyc-pr-guard >>>\n")
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value={"id": 1}):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert all(r.severity is Severity.INFO for r in res)


def test_missing_ruleset_yields_warning(one_repo: Path) -> None:
    (one_repo / ".git" / "hooks" / "pre-push").write_text("# >>> anvyc-pr-guard >>>\n")
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value=None), \
         patch("anvyc.checks.project_branch_protection._has_repo_access", return_value=True):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert any(r.severity is Severity.WARNING and "ruleset" in r.message for r in res)


def test_missing_hook_yields_warning(one_repo: Path) -> None:
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value={"id": 1}):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert any(r.severity is Severity.WARNING and "hook" in r.message for r in res)


def test_allowed_repo_skipped(one_repo: Path) -> None:
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_ALLOWED):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert res == []


def test_no_access_silent(one_repo: Path) -> None:
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value=None), \
         patch("anvyc.checks.project_branch_protection._has_repo_access", return_value=False):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert res == []  # whatap 등 접근 불가 → silent
