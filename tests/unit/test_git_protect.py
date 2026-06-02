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


def test_apply_dry_run_would_create_when_absent() -> None:
    # 1) rulesets 목록 비어있음, 2) repo probe 성공
    with patch("anvyc.core.git_protect._gh_api", side_effect=[(0, "[]", ""), (0, "16bitdo/anvyc", "")]):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=True)
    assert res.action == "would-create"


def test_apply_no_access_when_repo_probe_404() -> None:
    with patch("anvyc.core.git_protect._gh_api", side_effect=[(0, "[]", ""), (1, "", "404 Not Found")]):
        res = apply_ruleset("whatap", "argus", dry_run=True)
    assert res.action == "no-access"


def test_apply_creates_when_not_dry_run() -> None:
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(0, "[]", ""), (0, "16bitdo/anvyc", ""), (0, '{"id":9}', "")],
    ):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=False)
    assert res.action == "created"
