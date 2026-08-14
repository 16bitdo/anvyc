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
_FALLBACK = BranchPolicy(
    default_branch="main", protected_branches=("main",), push_to_main_allowed=False,
    pr_required=True, pr_reviewers_min=0, merge_strategy="squash", source="fallback",
)


@pytest.fixture(autouse=True)
def _gh_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 파일은 **인증이 정상일 때의 per-repo 판정** 을 시험한다.

    check 진입점의 gh 인증 preflight 를 고정하지 않으면 실행 머신의 gh 상태가 결과를
    바꾼다 — 인증된 개발 머신에선 통과하고 CI(gh 없음)에선 전부 빈 결과가 된다.

    autouse 인 이유: one_repo 를 쓰지 않는 시험(test_origin_less_skipped)도 같은
    관문을 지나며, 그 시험은 preflight 의 빈 결과 때문에 **엉뚱한 이유로** 통과할 수
    있다. preflight 자체의 동작은 test_project_branch_protection_auth.py 가 시험한다.
    """
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.gh_auth_state", lambda: "ok"
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
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "정합" in res[0].message


def test_missing_ruleset_yields_warning(one_repo: Path) -> None:
    (one_repo / ".git" / "hooks" / "pre-push").write_text("# >>> anvyc-pr-guard >>>\n")
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value=None), \
         patch("anvyc.checks.project_branch_protection.repo_admin", return_value=True):
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


def test_fallback_source_skipped(one_repo: Path) -> None:
    """role-based-ruleset 미발견(fallback) → 판단 근거 없음 → silent."""
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_FALLBACK):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert res == []


def test_not_admin_silent(one_repo: Path) -> None:
    """admin 아님(private 404 또는 public read-only) → enforce 불가 → silent."""
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value=None), \
         patch("anvyc.checks.project_branch_protection.repo_admin", return_value=False):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert res == []


def test_origin_less_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """origin 없는 repo → skip."""
    repo = tmp_path / "proj"
    (repo / ".git" / "hooks").mkdir(parents=True)
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.resolve_guard_targets",
        lambda project, root: [repo],
    )
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.origin_owner_repo",
        lambda d: None,
    )
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert res == []
