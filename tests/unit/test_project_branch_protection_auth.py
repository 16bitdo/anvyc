"""gh 인증 실패를 '권한 없음' 과 구분한다 — project-branch-protection 거짓 음성 차단.

`repo_admin()` 은 `rc == 0 and out == "true"` 라 모든 실패를 False 로 뭉갠다. 토큰이
만료되면 전 repo 가 "admin 아님" 으로 보여 check 가 `continue` 하고, 결과 0건 =
"문제 없음" 으로 보고된다.

2026-08-14 실사고: gh 토큰 만료 상태에서 doctor 가 `warning=0` 을 냈다. 재인증 후 같은
검사가 5건을 잡았다 — 0건은 정상이 아니라 **눈이 감긴 상태**였다.

인증 실패(401/403)와 404 는 **rc 가 둘 다 1** 이라 구분되지 않는다(실측). stderr 의
HTTP 코드만이 판별자다:
    무효 토큰 → `gh: Bad credentials (HTTP 401)`
    없는 repo → `gh: Not Found (HTTP 404)`
"""

from __future__ import annotations

from unittest.mock import patch

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.project_branch_protection import ProjectBranchProtectionCheck
from anvyc.core.git_protect import gh_auth_state


def _gh(rc: int, out: str = "", err: str = "") -> tuple[int, str, str]:
    return rc, out, err


def test_auth_state_ok() -> None:
    with patch("anvyc.core.git_protect._gh_api", return_value=_gh(0, "16bitdo\n")):
        assert gh_auth_state() == "ok"


def test_auth_state_401_is_unauthenticated() -> None:
    """만료·무효 토큰 — 실측 stderr 그대로."""
    with patch(
        "anvyc.core.git_protect._gh_api",
        return_value=_gh(1, "", "gh: Bad credentials (HTTP 401)\n"),
    ):
        assert gh_auth_state() == "unauthenticated"


def test_auth_state_403_is_unauthenticated() -> None:
    """스코프 부족 등 — 인증 계열로 함께 분류."""
    with patch(
        "anvyc.core.git_protect._gh_api",
        return_value=_gh(1, "", "gh: Forbidden (HTTP 403)\n"),
    ):
        assert gh_auth_state() == "unauthenticated"


def test_auth_state_404_is_not_unauthenticated() -> None:
    """경계 앵커 — 404 를 인증 실패로 오분류하면 안 된다.

    이게 없으면 "rc != 0 이면 unauthenticated" 인 구현도 위 시험들을 통과한다.
    """
    with patch(
        "anvyc.core.git_protect._gh_api",
        return_value=_gh(1, "", "gh: Not Found (HTTP 404)\n"),
    ):
        assert gh_auth_state() == "unavailable"


def test_auth_state_gh_missing_is_unavailable() -> None:
    """gh 미설치(rc=127) — 인증 문제가 아니다."""
    with patch(
        "anvyc.core.git_protect._gh_api", return_value=_gh(127, "", "gh CLI not found")
    ):
        assert gh_auth_state() == "unavailable"


def test_check_warns_when_unauthenticated() -> None:
    """인증 실패면 warning 1건 — 조용한 0건(=문제 없음) 대신 '알 수 없음' 을 알린다.

    repo 순회를 하지 않는 것도 함께 고정한다(전역 인증 실패에 per-repo 소음 금지).
    """
    check = ProjectBranchProtectionCheck()
    with (
        patch(
            "anvyc.checks.project_branch_protection.gh_auth_state",
            return_value="unauthenticated",
        ),
        patch("anvyc.checks.project_branch_protection.resolve_guard_targets") as targets,
    ):
        results = check.run(CheckContext())
    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert targets.call_count == 0


def test_check_silent_when_gh_unavailable() -> None:
    """gh 미설치·네트워크 불가는 조용히 — 그 머신에선 검사가 성립하지 않는다."""
    check = ProjectBranchProtectionCheck()
    with (
        patch(
            "anvyc.checks.project_branch_protection.gh_auth_state",
            return_value="unavailable",
        ),
        patch("anvyc.checks.project_branch_protection.resolve_guard_targets") as targets,
    ):
        results = check.run(CheckContext())
    assert results == []
    assert targets.call_count == 0


def test_check_proceeds_when_authenticated() -> None:
    """회귀 앵커 — 인증 정상이면 기존 경로(repo 순회)가 그대로 돈다."""
    check = ProjectBranchProtectionCheck()
    with (
        patch("anvyc.checks.project_branch_protection.gh_auth_state", return_value="ok"),
        patch(
            "anvyc.checks.project_branch_protection.resolve_guard_targets",
            return_value=[],
        ) as targets,
    ):
        results = check.run(CheckContext())
    assert results == []
    assert targets.call_count == 1
