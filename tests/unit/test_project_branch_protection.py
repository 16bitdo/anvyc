# tests/unit/test_project_branch_protection.py
"""Unit tests for project-branch-protection check."""
from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.checks.project_branch_protection import ProjectBranchProtectionCheck
from anvyc.core.branch_policy import BranchPolicy
from tests.unit._ruleset_fixtures import STATUS_CHECKS_RULE, pr_rules, ruleset_detail

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


@pytest.fixture(autouse=True)
def _ruleset_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """서버 ruleset 상세 조회를 "anvyc 가 만든 그대로" 로 고정한다.

    ruleset 이 있는 경로는 상세를 읽어 anvyc 기준과 비교한다. 고정하지 않으면 그 경로를
    지나는 시험이 실제 gh 를 부른다(CI 엔 gh 가 없다). 차이를 시험하는 쪽은 덮어쓴다.
    """
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.get_ruleset_detail",
        lambda owner, repo, rid: (ruleset_detail(), ""),
    )


@pytest.fixture(autouse=True)
def _repo_allows_every_merge_method(monkeypatch: pytest.MonkeyPatch) -> None:
    """저장소 머지 설정 조회를 "세 방식 모두 허용" 으로 고정한다(실제 gh 를 부르지 않게)."""
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.repo_merge_methods",
        lambda owner, repo: {"merge", "squash", "rebase"},
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


# ── 서버 ruleset 내용 ↔ anvyc 기준 ────────────────────────────────────────────
# `guard protect --apply` 는 ruleset 을 payload 로 통째로 덮어쓴다. 손으로 더한 규칙 ·
# 우회 권한자는 그때 사라지므로 --apply 전에 doctor 가 매일 보여 준다.


def _hooked(repo: Path) -> None:
    (repo / ".git" / "hooks" / "pre-push").write_text("# >>> anvyc-pr-guard >>>\n")


def test_ruleset_drift_yields_warning_naming_the_change(one_repo: Path) -> None:
    _hooked(one_repo)
    asked: list[Any] = []

    def drifted(owner: str, repo: str, rid: Any) -> tuple[dict[str, Any], str]:
        asked.append((owner, repo, rid))
        bypass = [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
        rules = [*ruleset_detail()["rules"], STATUS_CHECKS_RULE]
        return ruleset_detail(rules=rules, bypass_actors=bypass), ""

    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value={"id": 7}), \
         patch("anvyc.checks.project_branch_protection.get_ruleset_detail", side_effect=drifted):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert asked == [("16bitdo", "proj", 7)]  # LIST 가 준 id 로 상세를 읽는다
    assert [r.severity for r in res] == [Severity.WARNING]  # 정합으로 세지 않는다
    assert "required_status_checks" in res[0].message
    assert "bypass_actors" in res[0].message
    # 전체 --apply 를 권하면 바로 그 덮어쓰기를 부른다 — 이 repo 의 dry-run 으로 차이를 보게 한다.
    assert res[0].suggestion is not None and f"--project {one_repo}" in res[0].suggestion


def test_ruleset_drift_compares_against_manifest_review_count(one_repo: Path) -> None:
    # manifest 가 리뷰 1명을 요구하는데 서버 ruleset 은 0 이면 --apply 가 바꿀 내용이다.
    _hooked(one_repo)
    needs_review = dataclasses.replace(_PROTECTED, pr_reviewers_min=1)
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=needs_review), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value={"id": 7}):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert [r.severity for r in res] == [Severity.WARNING]
    assert "required_approving_review_count" in res[0].message


def test_unreadable_ruleset_detail_is_not_reported_aligned(one_repo: Path) -> None:
    # 내용을 못 읽었으면 정합인지 알 수 없다 — "정합" 으로 세면 확인 안 된 repo 가 초록이 된다.
    _hooked(one_repo)
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value={"id": 7}), \
         patch(
             "anvyc.checks.project_branch_protection.get_ruleset_detail",
             return_value=(None, "gh: Server Error (HTTP 502)"),
         ):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert [r.severity for r in res] == [Severity.WARNING]
    assert "HTTP 502" in res[0].message


def test_missing_ruleset_yields_warning(one_repo: Path) -> None:
    (one_repo / ".git" / "hooks" / "pre-push").write_text("# >>> anvyc-pr-guard >>>\n")
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value=None), \
         patch("anvyc.checks.project_branch_protection.repo_admin", return_value=True), \
         patch("anvyc.checks.project_branch_protection.repo_archived", return_value=False):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert any(r.severity is Severity.WARNING and "ruleset" in r.message for r in res)


def _missing_ruleset_suggestion(repo: Path) -> str:
    (repo / ".git" / "hooks" / "pre-push").write_text("# >>> anvyc-pr-guard >>>\n")
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value=None), \
         patch("anvyc.checks.project_branch_protection.repo_admin", return_value=True), \
         patch("anvyc.checks.project_branch_protection.repo_archived", return_value=False):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert [r.severity for r in res] == [Severity.WARNING]
    assert res[0].suggestion is not None
    return res[0].suggestion


def test_missing_ruleset_suggests_this_repo_only(one_repo: Path) -> None:
    # `--project` 없는 `guard protect --apply` 는 모든 대상 repo 의 ruleset 을 덮어쓴다 —
    # 다른 repo 의 손 설정까지 지우지 않게 이 repo 만 지정한다.
    suggestion = _missing_ruleset_suggestion(one_repo)
    assert suggestion == f"anvyc guard protect --project {one_repo} --apply"


def test_suggestion_shortens_home_path(one_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 홈 아래 repo 는 `~` 로 줄여 위치(location) 표시와 맞춘다 — guard protect 가 --project 를
    # expanduser 하므로 그대로 실행된다.
    monkeypatch.setenv("HOME", str(one_repo.parent))
    suggestion = _missing_ruleset_suggestion(one_repo)
    assert suggestion == "anvyc guard protect --project ~/proj --apply"


def test_suggestion_keeps_path_when_home_is_only_a_name_prefix(
    one_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 홈이 `.../pro` 이면 `.../proj` 는 홈 아래가 아니다 — `~j` 같은 엉뚱한 경로를 만들면 안 된다.
    monkeypatch.setenv("HOME", str(one_repo)[:-1])
    suggestion = _missing_ruleset_suggestion(one_repo)
    assert suggestion == f"anvyc guard protect --project {one_repo} --apply"


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


def _run_with_ruleset_ok() -> list[CheckResult]:
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


# ── 허용 머지 방식 — manifest 에 직접 적은 merge_strategy ─────────────────────

_DECLARED_MERGE = dataclasses.replace(
    _PROTECTED, merge_strategy="merge", declared=frozenset({"merge_strategy"})
)


def _run_with(policy: BranchPolicy, detail: dict[str, Any] | None = None) -> list[CheckResult]:
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=policy), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value={"id": 7}), \
         patch(
             "anvyc.checks.project_branch_protection.get_ruleset_detail",
             return_value=(detail if detail is not None else ruleset_detail(), ""),
         ):
        return ProjectBranchProtectionCheck().run(CheckContext())


def test_declared_merge_strategy_is_compared(one_repo: Path) -> None:
    # 서버 ruleset 은 기본값 3종인데 manifest 는 merge 만 — guard protect --apply 가 좁힐 내용이다.
    _hooked(one_repo)
    res = _run_with(_DECLARED_MERGE)
    assert [r.severity for r in res] == [Severity.WARNING]
    assert "allowed_merge_methods" in res[0].message


def test_inherited_merge_strategy_is_not_enforced(one_repo: Path) -> None:
    # _PROTECTED 의 squash 는 항목에 안 적은(defaults 상속) 값이다 — 기본값 3종 ruleset 은 정합.
    _hooked(one_repo)
    res = _run_with(_PROTECTED)
    assert [r.severity for r in res] == [Severity.INFO]


def test_repo_settings_blocking_declared_method_yields_warning(
    one_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ruleset 은 merge 만, 저장소는 merge commit 을 꺼 뒀다 — 어떤 방식으로도 머지할 수 없다.
    _hooked(one_repo)
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.repo_merge_methods",
        lambda owner, repo: {"squash", "rebase"},
    )
    aligned = ruleset_detail(rules=pr_rules(allowed_merge_methods=["merge"]))
    res = _run_with(_DECLARED_MERGE, aligned)
    assert [r.severity for r in res] == [Severity.WARNING]
    assert "merge_strategy" in res[0].message
    assert res[0].suggestion is not None and "merge_strategy" in res[0].suggestion


def test_unreadable_repo_settings_is_not_reported_aligned(
    one_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hooked(one_repo)
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.repo_merge_methods", lambda owner, repo: None
    )
    aligned = ruleset_detail(rules=pr_rules(allowed_merge_methods=["merge"]))
    res = _run_with(_DECLARED_MERGE, aligned)
    assert [r.severity for r in res] == [Severity.WARNING]
    # ruleset 은 merge 로 이미 맞다 — 경고는 머지 설정을 못 읽어서여야 한다
    assert "머지 설정" in res[0].message
    assert "allowed_merge_methods" not in res[0].message


def test_archived_repo_gets_no_merge_settings_warning(
    one_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # archived 는 저장소 설정도 바꿀 수 없다 — 조치 불가능한 경고를 매일 내지 않는다.
    _hooked(one_repo)
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.repo_merge_methods",
        lambda owner, repo: {"squash", "rebase"},
    )
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_DECLARED_MERGE), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value=None), \
         patch("anvyc.checks.project_branch_protection.repo_admin", return_value=True), \
         patch("anvyc.checks.project_branch_protection.repo_archived", return_value=True):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert not any(r.severity is Severity.WARNING for r in res)
