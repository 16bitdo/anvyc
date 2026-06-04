# tests/unit/test_git_protect.py
"""Unit tests for anvyc.core.git_protect."""
from __future__ import annotations

import json
from unittest.mock import patch

from anvyc.core.git_protect import (
    RULESET_NAME,
    apply_ruleset,
    build_ruleset_payload,
    get_ruleset,
)


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
    listing = json.dumps([{"id": 7, "name": RULESET_NAME}])
    with patch("anvyc.core.git_protect._gh_api", side_effect=[(0, listing, "")]):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=True)
    assert res.action == "exists"
    assert "required_reviews=0" in res.detail


def test_apply_updates_existing_non_dry() -> None:
    listing = json.dumps([{"id": 7, "name": RULESET_NAME}])
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(0, listing, ""), (0, "", "")],
    ):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=False)
    assert res.action == "updated"
    assert "required_reviews=0" in res.detail
