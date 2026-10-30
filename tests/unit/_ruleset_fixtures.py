# tests/unit/_ruleset_fixtures.py
"""anvyc-pr-required ruleset 의 GitHub 응답 픽스처 — git_protect · doctor check 테스트가 함께 쓴다."""
from __future__ import annotations

import copy
import json
from typing import Any

from anvyc.core.git_protect import RULESET_NAME

# 손으로 더한 규칙 — rbr 의 CI 필수 체크(2026-10-30)와 같은 모양.
STATUS_CHECKS_RULE: dict[str, Any] = {
    "type": "required_status_checks",
    "parameters": {
        "strict_required_status_checks_policy": False,
        "do_not_enforce_on_create": False,
        "required_status_checks": [{"context": "ci-ok", "integration_id": 15368}],
    },
}


def ruleset_detail(**changes: Any) -> dict[str, Any]:
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


def pr_rules(**params: Any) -> list[dict[str, Any]]:
    """ruleset_detail() 의 rules 에서 pull_request 파라미터만 바꾼 사본."""
    rules: list[dict[str, Any]] = copy.deepcopy(ruleset_detail()["rules"])
    rules[2]["parameters"].update(params)
    return rules


def listing() -> str:
    """GET rulesets(LIST) 응답 — 요약만 있고 rules 는 없다."""
    return json.dumps([{"id": 7, "name": RULESET_NAME}])
