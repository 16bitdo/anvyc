# tests/unit/test_git_protect.py
"""Unit tests for anvyc.core.git_protect."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from anvyc.cli import app
from anvyc.core.branch_policy import BranchPolicy
from anvyc.core.git_protect import (
    RULESET_NAME,
    apply_ruleset,
    build_ruleset_payload,
    diff_ruleset,
    get_ruleset,
    ruleset_changes,
)
from tests.unit._ruleset_fixtures import STATUS_CHECKS_RULE as _STATUS_CHECKS_RULE
from tests.unit._ruleset_fixtures import listing as _listing
from tests.unit._ruleset_fixtures import pr_rules as _pr_rules
from tests.unit._ruleset_fixtures import ruleset_detail as _detail


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


@pytest.mark.parametrize(
    ("changes", "tokens"),
    [
        ({"enforcement": "disabled"}, ("enforcement",)),
        (
            {
                "bypass_actors": [
                    {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}
                ]
            },
            ("bypass_actors",),
        ),
        ({"rules": [*_detail()["rules"], _STATUS_CHECKS_RULE]}, ("required_status_checks", "삭제")),
        (
            {"rules": [r for r in _detail()["rules"] if r["type"] != "deletion"]},
            ("deletion", "추가"),
        ),
        (
            {"rules": _pr_rules(required_approving_review_count=1)},
            ("pull_request", "required_approving_review_count"),
        ),
        (
            {"rules": _pr_rules(allowed_merge_methods=["merge"])},
            ("pull_request", "allowed_merge_methods"),
        ),
    ],
    ids=["top-level", "bypass", "rule-removed", "rule-added", "managed-param", "unsent-param"],
)
def test_ruleset_changes_label_names_what_changes(
    changes: dict[str, Any], tokens: tuple[str, ...]
) -> None:
    # doctor 는 한 줄 요약에 label 만 쓴다 — 값 없이도 무엇이 바뀌는지, 규칙이면 사라지는지
    # 생기는지 알 수 있어야 한다.
    found = ruleset_changes(_detail(**changes), build_ruleset_payload(required_reviews=0))
    assert len(found) == 1, found
    assert all(t in found[0].label for t in tokens), found[0].label
    assert "{" not in found[0].label  # 값(JSON)은 label 에 싣지 않는다


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


# ── 허용 머지 방식 — manifest 에 직접 적은 merge_strategy ─────────────────────
# ruleset 의 allowed_merge_methods 와 저장소 설정(allow_*_merge)이 겹치는 방식만 쓸 수 있다.
# 겹치지 않으면 머지가 아예 막히므로, 그렇게 될 ruleset 은 쓰지 않는다.

_SETTINGS_ARGS = [
    "repos/16bitdo/anvyc",
    "--jq",
    "{allow_merge_commit, allow_squash_merge, allow_rebase_merge}",
]
_ALL_ALLOWED = {"allow_merge_commit": True, "allow_squash_merge": True, "allow_rebase_merge": True}


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("merge", ["merge"]),
        ("squash", ["squash"]),
        ("rebase", ["rebase"]),
        (None, None),  # 강제할 값 없음 — 지금처럼 서버 기본값
        ("fast-forward", None),  # 모르는 값은 강제하지 않는다
    ],
    ids=["merge", "squash", "rebase", "none", "unknown"],
)
def test_payload_allowed_merge_methods_follow_strategy(
    strategy: str | None, expected: list[str] | None
) -> None:
    payload = build_ruleset_payload(required_reviews=0, merge_strategy=strategy)
    pr = next(r for r in payload["rules"] if r["type"] == "pull_request")
    assert pr["parameters"].get("allowed_merge_methods") == expected


def _fake_gh_with_settings(
    settings: dict[str, bool] | None,
    *,
    existing: bool,
    sent: list[tuple[list[str], str | None]],
) -> Any:
    def fake(
        args: list[str], *, input_str: str | None = None, timeout: int = 20
    ) -> tuple[int, str, str]:
        sent.append((list(args), input_str))
        if args == ["repos/16bitdo/anvyc/rulesets"]:
            return (0, _listing() if existing else "[]", "")
        if args == _SETTINGS_ARGS:
            if settings is None:
                return (1, "", "gh: Server Error (HTTP 502)")
            return (0, json.dumps(settings), "")
        if args == ["repos/16bitdo/anvyc/rulesets/7"]:
            return (0, json.dumps(_detail()), "")
        if "--method" in args:
            return (0, "{}", "")
        raise AssertionError(f"unexpected gh call: {args}")

    return fake


def test_apply_writes_declared_merge_methods() -> None:
    sent: list[tuple[list[str], str | None]] = []
    fake = _fake_gh_with_settings(_ALL_ALLOWED, existing=True, sent=sent)
    with patch("anvyc.core.git_protect._gh_api", side_effect=fake):
        res = apply_ruleset("16bitdo", "anvyc", merge_strategy="merge", dry_run=False)
    assert res.action == "updated"
    bodies = [body for args, body in sent if "PUT" in args]
    assert len(bodies) == 1 and bodies[0] is not None
    pr = next(r for r in json.loads(bodies[0])["rules"] if r["type"] == "pull_request")
    assert pr["parameters"]["allowed_merge_methods"] == ["merge"]
    # 서버 기본값 3종 → merge 만: 덮어쓰기 전에 보이는 차이에도 나온다
    assert any("allowed_merge_methods" in line for line in res.diff)


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "apply"])
@pytest.mark.parametrize("existing", [True, False], ids=["update", "create"])
def test_apply_refuses_when_repo_settings_block_the_method(existing: bool, dry_run: bool) -> None:
    # 저장소가 merge commit 을 꺼 뒀는데 ruleset 을 merge 만 허용으로 만들면 머지가 아예 막힌다.
    sent: list[tuple[list[str], str | None]] = []
    blocked = {**_ALL_ALLOWED, "allow_merge_commit": False}
    fake = _fake_gh_with_settings(blocked, existing=existing, sent=sent)
    with patch("anvyc.core.git_protect._gh_api", side_effect=fake):
        res = apply_ruleset("16bitdo", "anvyc", merge_strategy="merge", dry_run=dry_run)
    assert res.action == "error"
    assert not any("--method" in args for args, _ in sent)  # 쓰지 않았다


def test_apply_refuses_when_repo_settings_unreadable() -> None:
    # 설정을 못 읽으면 머지가 막힐지 알 수 없다 — 쓰지 않는다.
    sent: list[tuple[list[str], str | None]] = []
    fake = _fake_gh_with_settings(None, existing=True, sent=sent)
    with patch("anvyc.core.git_protect._gh_api", side_effect=fake):
        res = apply_ruleset("16bitdo", "anvyc", merge_strategy="merge", dry_run=False)
    assert res.action == "error"
    assert not any("--method" in args for args, _ in sent)


def test_apply_skips_settings_check_without_merge_strategy() -> None:
    # 강제할 머지 방식이 없으면 저장소 설정을 볼 이유가 없다(호출 예산).
    sent: list[tuple[list[str], str | None]] = []
    fake = _fake_gh_with_settings(_ALL_ALLOWED, existing=True, sent=sent)
    with patch("anvyc.core.git_protect._gh_api", side_effect=fake):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=False)
    assert res.action == "updated"
    assert not any(args == _SETTINGS_ARGS for args, _ in sent)


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
        tuple(_SETTINGS_ARGS): (0, json.dumps(_ALL_ALLOWED), ""),
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


def test_cli_enforces_declared_merge_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # manifest 에 merge_strategy 를 직접 적은 repo 는 guard protect 가 그 방식만 허용하게 만든다.
    declared = BranchPolicy(
        default_branch="main",
        protected_branches=("main",),
        push_to_main_allowed=False,
        pr_required=True,
        pr_reviewers_min=0,
        merge_strategy="merge",
        source="manifest",
        declared=frozenset({"merge_strategy"}),
    )
    monkeypatch.setattr("anvyc.core.branch_policy.resolve_policy", lambda repo: declared)
    calls: list[list[str]] = []
    args = ["guard", "protect", "--project", str(_repo_with_origin(tmp_path))]
    with patch("anvyc.core.git_protect._gh_api", side_effect=_fake_gh_for_cli(calls, _detail())):
        result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "would-update" in result.stdout
    assert "allowed_merge_methods" in result.stdout
