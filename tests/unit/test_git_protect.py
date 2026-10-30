# tests/unit/test_git_protect.py
"""Unit tests for anvyc.core.git_protect."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from anvyc.cli import app
from anvyc.core.git_protect import (
    RULESET_NAME,
    apply_ruleset,
    build_ruleset_payload,
    diff_ruleset,
    get_ruleset,
)

# 손으로 더한 규칙 — rbr 의 CI 필수 체크(2026-10-30)와 같은 모양.
_STATUS_CHECKS_RULE: dict[str, Any] = {
    "type": "required_status_checks",
    "parameters": {
        "strict_required_status_checks_policy": False,
        "do_not_enforce_on_create": False,
        "required_status_checks": [{"context": "ci-ok", "integration_id": 15368}],
    },
}


def _detail(**changes: Any) -> dict[str, Any]:
    """GET rulesets/{id} 응답 — anvyc 가 만든 뒤 아무도 손대지 않은 ruleset.

    2026-10-30 실제 응답(16bitdo 의 anvyc · okr · reflection · role-based-ruleset 4곳이
    같았다)과 같은 모양이다. pull_request 의 required_reviewers ·
    require_extra_approval_for_unattributed_changes · allowed_merge_methods 는 payload 에
    없고 서버가 채운 기본값이다.
    """
    detail: dict[str, Any] = {
        "id": 7,
        "name": RULESET_NAME,
        "target": "branch",
        "source_type": "Repository",
        "source": "16bitdo/anvyc",
        "enforcement": "active",
        "conditions": {"ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "required_reviewers": [],
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                    "require_extra_approval_for_unattributed_changes": True,
                    "allowed_merge_methods": ["merge", "squash", "rebase"],
                },
            },
        ],
        "node_id": "RRS_test",
        "created_at": "2026-06-02T12:02:18.028+09:00",
        "updated_at": "2026-06-02T12:02:18.064+09:00",
        "bypass_actors": [],
        "current_user_can_bypass": "never",
        "_links": {
            "self": {"href": "https://api.github.com/repos/16bitdo/anvyc/rulesets/7"},
            "html": {"href": "https://github.com/16bitdo/anvyc/rules/7"},
        },
    }
    detail.update(changes)
    return detail


def _pr_rules(**params: Any) -> list[dict[str, Any]]:
    """_detail() 의 rules 에서 pull_request 파라미터만 바꾼 사본."""
    rules: list[dict[str, Any]] = copy.deepcopy(_detail()["rules"])
    rules[2]["parameters"].update(params)
    return rules


def _listing() -> str:
    return json.dumps([{"id": 7, "name": RULESET_NAME}])


def test_payload_blocks_direct_push_with_pr_rule() -> None:
    p = build_ruleset_payload(required_reviews=0)
    assert p["name"] == RULESET_NAME
    assert p["enforcement"] == "active"
    assert p["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    types = {r["type"] for r in p["rules"]}
    assert {"pull_request", "non_fast_forward", "deletion"} <= types
    pr = next(r for r in p["rules"] if r["type"] == "pull_request")
    assert pr["parameters"]["required_approving_review_count"] == 0


def test_get_ruleset_matches_by_name() -> None:
    listing = json.dumps([{"id": 7, "name": RULESET_NAME}, {"id": 8, "name": "other"}])
    with patch("anvyc.core.git_protect._gh_api", return_value=(0, listing, "")):
        rs = get_ruleset("16bitdo", "anvyc")
    assert rs is not None and rs["id"] == 7


def test_get_ruleset_none_on_list_failure() -> None:
    with patch("anvyc.core.git_protect._gh_api", return_value=(1, "", "500 err")):
        assert get_ruleset("16bitdo", "anvyc") is None


def test_apply_dry_run_would_create_when_absent() -> None:
    with patch("anvyc.core.git_protect._gh_api", side_effect=[(0, "[]", "")]):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=True)
    assert res.action == "would-create"
    assert "required_reviews=0" in res.detail


def test_apply_dry_run_detail_shows_required_reviews() -> None:
    # dry-run 출력에 적용 예정 required_reviews 값이 보여야 한다 (defaults 상속 오적용 사전 감지)
    with patch("anvyc.core.git_protect._gh_api", side_effect=[(0, "[]", "")]):
        res = apply_ruleset("16bitdo", "anvyc", required_reviews=1, dry_run=True)
    assert res.action == "would-create"
    assert "required_reviews=1" in res.detail


def test_apply_no_access_when_list_and_probe_404() -> None:
    # LIST 404 + repo probe 404 → no-access
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(1, "", "404 Not Found"), (1, "", "404 Not Found")],
    ):
        res = apply_ruleset("whatap", "argus", dry_run=True)
    assert res.action == "no-access"


def test_apply_error_when_list_fails_but_repo_accessible() -> None:
    # LIST 실패(일시오류) + repo probe 성공 → error (POST 안 함, 중복 방지)
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(1, "", "500"), (0, "16bitdo/anvyc", "")],
    ):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=False)
    assert res.action == "error"


def test_apply_creates_when_not_dry_run() -> None:
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(0, "[]", ""), (0, '{"id":9}', "")],
    ):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=False)
    assert res.action == "created"
    assert "required_reviews=0" in res.detail


def test_apply_post_error() -> None:
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(0, "[]", ""), (1, "", "422 boom")],
    ):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=False)
    assert res.action == "error"
    assert "422 boom" in res.detail  # 실패 시 detail 은 오류 메시지 유지


def test_apply_exists_when_present_dry_run() -> None:
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(0, _listing(), ""), (0, json.dumps(_detail()), "")],
    ):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=True)
    assert res.action == "exists"
    assert res.diff == []
    assert "required_reviews=0" in res.detail


def test_apply_updates_existing_non_dry() -> None:
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(0, _listing(), ""), (0, json.dumps(_detail()), ""), (0, "", "")],
    ):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=False)
    assert res.action == "updated"
    assert "required_reviews=0" in res.detail


# ── 덮어쓰기 전 차이 ──────────────────────────────────────────────────────────
# PUT 은 ruleset 을 payload 로 통째로 바꾼다. 손으로 더한 규칙 · 우회 권한자 · 비상시
# 끈 enforcement 가 알림 없이 사라지지 않도록 바뀌는 것을 먼저 보여 준다.


def test_diff_is_empty_for_untouched_ruleset() -> None:
    # 손대지 않은 ruleset 에서 경고가 나면 매번 무시하게 된다 — 조회 전용 필드(id · _links ·
    # 시각), 키 순서, 서버가 채운 기본값은 차이가 아니다.
    assert diff_ruleset(_detail(), build_ruleset_payload(required_reviews=0)) == []


@pytest.mark.parametrize(
    ("changes", "tokens"),
    [
        ({"enforcement": "disabled"}, ("enforcement", "disabled", "active")),
        (
            {
                "bypass_actors": [
                    {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}
                ]
            },
            ("bypass_actors", "RepositoryRole"),
        ),
        (
            {
                "conditions": {
                    "ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH", "refs/heads/rel"]}
                }
            },
            ("conditions", "refs/heads/rel"),
        ),
        (
            {"rules": [*_detail()["rules"], _STATUS_CHECKS_RULE]},
            ("required_status_checks", "ci-ok"),
        ),
        (
            {"rules": _pr_rules(required_approving_review_count=1)},
            ("required_approving_review_count", "1", "0"),
        ),
        (
            {"rules": _pr_rules(allowed_merge_methods=["merge"])},
            ("allowed_merge_methods", "squash"),
        ),
        ({"rules": _pr_rules(future_param=True)}, ("future_param",)),
        (
            {"rules": [r for r in _detail()["rules"] if r["type"] != "deletion"]},
            ("deletion",),
        ),
    ],
    ids=[
        "enforcement",
        "bypass-actors",
        "conditions",
        "rule-not-in-payload",
        "managed-param",
        "unsent-param-reset-to-default",
        "unsent-param-default-unknown",
        "rule-only-in-payload",
    ],
)
def test_diff_reports_each_change_put_would_make(
    changes: dict[str, Any], tokens: tuple[str, ...]
) -> None:
    lines = diff_ruleset(_detail(**changes), build_ruleset_payload(required_reviews=0))
    assert len(lines) == 1, lines
    assert all(t in lines[0] for t in tokens), lines


def test_apply_dry_run_would_update_shows_diff() -> None:
    detail = _detail(rules=[*_detail()["rules"], _STATUS_CHECKS_RULE])
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(0, _listing(), ""), (0, json.dumps(detail), "")],
    ):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=True)
    assert res.action == "would-update"
    assert any("required_status_checks" in line for line in res.diff)


def test_apply_warns_with_diff_before_put() -> None:
    detail = json.dumps(_detail(rules=[*_detail()["rules"], _STATUS_CHECKS_RULE]))
    events: list[str] = []
    warned: list[list[str]] = []

    def fake_gh(
        args: list[str], *, input_str: str | None = None, timeout: int = 20
    ) -> tuple[int, str, str]:
        if "PUT" in args:
            events.append("put")
            return (0, "", "")
        if args == ["repos/16bitdo/anvyc/rulesets"]:
            return (0, _listing(), "")
        if args == ["repos/16bitdo/anvyc/rulesets/7"]:
            return (0, detail, "")
        raise AssertionError(f"unexpected gh call: {args}")

    def on_overwrite(lines: list[str]) -> None:
        events.append("warn")
        warned.append(lines)

    with patch("anvyc.core.git_protect._gh_api", side_effect=fake_gh):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=False, on_overwrite=on_overwrite)
    assert events == ["warn", "put"]
    assert any("required_status_checks" in line for line in warned[0])
    assert res.action == "updated"


def test_apply_does_not_warn_when_nothing_changes() -> None:
    warned: list[list[str]] = []
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(0, _listing(), ""), (0, json.dumps(_detail()), ""), (0, "", "")],
    ):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=False, on_overwrite=warned.append)
    assert warned == []
    assert res.action == "updated"


@pytest.mark.parametrize(
    "detail_response",
    [(1, "", "gh: Server Error (HTTP 502)"), (0, "<html>not json</html>", "")],
    ids=["gh-error", "not-json"],
)
def test_apply_refuses_to_overwrite_when_detail_unreadable(
    detail_response: tuple[int, str, str],
) -> None:
    # 기존 내용을 못 읽으면 무엇을 지우는지 보여 줄 수 없다 — 덮어쓰지 않는다.
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(0, _listing(), ""), detail_response],
    ) as gh:
        res = apply_ruleset("16bitdo", "anvyc", dry_run=False)
    assert res.action == "error"
    sent = [c.args[0] for c in gh.call_args_list]
    assert sent[1] == ["repos/16bitdo/anvyc/rulesets/7"]  # 두 번째 호출은 상세 조회
    assert not any("PUT" in a for a in sent)  # PUT 을 보내지 않았다


# ── CLI: guard protect 출력 ───────────────────────────────────────────────────


def _repo_with_origin(tmp_path: Path) -> Path:
    proj = tmp_path / "anvyc"
    (proj / ".git").mkdir(parents=True)
    (proj / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:16bitdo/anvyc.git\n', encoding="utf-8"
    )
    return proj


def _fake_gh_for_cli(calls: list[list[str]], detail: dict[str, Any]) -> Any:
    table: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("repos/16bitdo/anvyc", "--jq", ".permissions.admin"): (0, "true\n", ""),
        ("repos/16bitdo/anvyc", "--jq", ".archived"): (0, "false\n", ""),
        ("repos/16bitdo/anvyc/rulesets",): (0, _listing(), ""),
        ("repos/16bitdo/anvyc/rulesets/7",): (0, json.dumps(detail), ""),
        ("repos/16bitdo/anvyc/rulesets/7", "--method", "PUT", "--input", "-"): (0, "{}", ""),
    }

    def fake(
        args: list[str], *, input_str: str | None = None, timeout: int = 20
    ) -> tuple[int, str, str]:
        calls.append(list(args))
        return table[tuple(args)]

    return fake


@pytest.mark.parametrize("apply", [True, False], ids=["apply", "dry-run"])
def test_cli_prints_diff_before_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, apply: bool
) -> None:
    # 정책 lookup 스크립트가 없으면 fallback(main push 금지 · 리뷰 0)이다.
    monkeypatch.setenv("ANVYC_RULESET_DIR", str(tmp_path / "no-rbr"))
    detail = _detail(rules=[*_detail()["rules"], _STATUS_CHECKS_RULE])
    calls: list[list[str]] = []
    args = ["guard", "protect", "--project", str(_repo_with_origin(tmp_path))]
    with patch("anvyc.core.git_protect._gh_api", side_effect=_fake_gh_for_cli(calls, detail)):
        result = CliRunner().invoke(app, [*args, "--apply"] if apply else args)
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "ci-ok" in out
    put_sent = any("PUT" in c for c in calls)
    if apply:
        assert put_sent
        assert out.index("required_status_checks") < out.index("updated")
    else:
        assert not put_sent
        assert "would-update" in out
