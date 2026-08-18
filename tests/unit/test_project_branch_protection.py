# tests/unit/test_project_branch_protection.py
"""Unit tests for project-branch-protection check."""
from __future__ import annotations

import subprocess
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
         patch("anvyc.checks.project_branch_protection.repo_admin", return_value=True), \
         patch("anvyc.checks.project_branch_protection.repo_archived", return_value=False):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert any(r.severity is Severity.WARNING and "ruleset" in r.message for r in res)


def test_archived_repo_skipped(one_repo: Path) -> None:
    """archived repo 는 ruleset 설정이 **영원히 불가능**하다 — 조치 불가 WARN 을 내지 않는다.

    GitHub 은 archived repo 의 쓰기를 403 으로 막는다(2026-08-16 실측: `guard protect
    --apply` 가 16bitdo/cc-inspect 에서 "Repository was archived so is read-only.
    (HTTP 403)"). 그런데 doctor 는 매일 그 repo 를 WARNING 으로 올리면서 해소책으로
    **실패하는 바로 그 명령**을 안내했다. 조치 불가능한 상시 경고는 무시를 훈련시켜
    진짜 신호까지 함께 묻는다.
    """
    (one_repo / ".git" / "hooks" / "pre-push").write_text("# >>> anvyc-pr-guard >>>\n")
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value=None), \
         patch("anvyc.checks.project_branch_protection.repo_admin", return_value=True), \
         patch("anvyc.checks.project_branch_protection.repo_archived", return_value=True):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert not any(r.severity is Severity.WARNING for r in res)


def test_archived_not_queried_when_aligned(one_repo: Path) -> None:
    """정합 repo 에서는 archived 조회를 하지 않는다 — repo 당 gh api 예산을 지킨다.

    이 앵커가 없으면 '전 repo 마다 API 1회 추가' 회귀가 조용히 들어온다(모듈 헤더가
    선언한 '보호 대상 repo 당 gh api 1~2회' 계약).
    """
    (one_repo / ".git" / "hooks" / "pre-push").write_text("# >>> anvyc-pr-guard >>>\n")
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value={"id": 1}), \
         patch("anvyc.checks.project_branch_protection.repo_archived") as m_arch:
        ProjectBranchProtectionCheck().run(CheckContext())
    m_arch.assert_not_called()


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


@pytest.fixture
def tracked_hooks_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """core.hooksPath 가 worktree 내부(tracked)를 가리키는 실 repo — 검사 대상으로 등록."""
    repo = tmp_path / "proj"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "githooks").mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "config", "core.hooksPath", "githooks"], check=True
    )
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.resolve_guard_targets",
        lambda project, root: [repo],
    )
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.origin_owner_repo",
        lambda d: ("16bitdo", "proj"),
    )
    return repo


def _run_with_ruleset_ok() -> list:
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value={"id": 1}):
        return ProjectBranchProtectionCheck().run(CheckContext())


def test_tracked_hookspath_without_guard_yields_warning(tracked_hooks_repo: Path) -> None:
    """tracked hooksPath 여도 가드가 **실제로** 있는지 확인한다.

    anvyc 는 tracked 훅을 clobber 하지 않고 skip 한다. 그때 "해당 repo 도구 책임"
    이라며 무조건 정합 처리하면, 그 책임을 아무도 지지 않은 repo 가 초록으로
    보고된다 (2026-08-18 anvyx — githooks/pre-push 에 가드가 없는데 doctor 는 정합).
    """
    (tracked_hooks_repo / "githooks" / "pre-push").write_text("#!/bin/sh\necho lint only\n")
    res = _run_with_ruleset_ok()
    assert any(r.severity is Severity.WARNING and "가드" in r.message for r in res)


def test_tracked_hookspath_suggestion_omits_guard_install(tracked_hooks_repo: Path) -> None:
    """tracked 케이스에 `anvyc guard install` 을 해소책으로 안내하지 않는다.

    그 명령은 tracked hooksPath 에서 skipped-tracked-hooks 로 **아무 일도 하지 않는다**.
    실패하는 명령을 해소책으로 걸면 경고 무시가 훈련된다 — archived repo 에서 얻은 교훈.
    """
    (tracked_hooks_repo / "githooks" / "pre-push").write_text("#!/bin/sh\necho lint only\n")
    res = _run_with_ruleset_ok()
    warn = next(r for r in res if r.severity is Severity.WARNING)
    assert "guard install" not in (warn.suggestion or "")


def test_tracked_hookspath_with_guard_is_aligned(tracked_hooks_repo: Path) -> None:
    """tracked 훅이 가드 블록을 담고 있으면 정합 — 무조건 경고로 뒤집지 않기 위한 앵커.

    (RED 로 유도된 시험이 아니라, 위 두 시험의 과교정을 막는 반대 방향 구속이다.)
    """
    (tracked_hooks_repo / "githooks" / "pre-push").write_text(
        "#!/bin/sh\n# >>> anvyc-pr-guard >>>\n"
    )
    res = _run_with_ruleset_ok()
    assert not any(r.severity is Severity.WARNING for r in res)
