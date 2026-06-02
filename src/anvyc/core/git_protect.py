# src/anvyc/core/git_protect.py
"""GitHub repository ruleset 으로 서버측 PR 강제를 적용한다.

`anvyc guard protect` 가 활성 gh 계정으로 대상 repo 에 `anvyc-pr-required`
ruleset 을 생성/갱신한다. 직접 push 는 pull_request 규칙으로 차단된다.
접근 불가(whatap 등 404)는 no-access 로 분류해 silent 처리한다.

rulesets LIST 호출의 rc 를 직접 보고 분기한다(LIST 실패를 "ruleset 없음" 으로
오인해 중복 POST 하는 것을 방지).
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Literal

RULESET_NAME = "anvyc-pr-required"

ProtectAction = Literal[
    "created", "updated", "exists", "would-create", "no-access", "error"
]


def build_ruleset_payload(*, required_reviews: int = 0) -> dict[str, Any]:
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": required_reviews,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                },
            },
        ],
        "bypass_actors": [],
    }


def _gh_api(
    args: list[str], *, input_str: str | None = None, timeout: int = 20
) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["gh", "api", *args],
            input=input_str, capture_output=True, text=True, check=False, timeout=timeout,
        )
    except FileNotFoundError:
        return 127, "", "gh CLI not found"
    except subprocess.SubprocessError as e:  # TimeoutExpired ⊂ SubprocessError
        return 1, "", str(e)
    return proc.returncode, proc.stdout, proc.stderr


def _list_rulesets(owner: str, repo: str) -> tuple[int, list[dict[str, Any]]]:
    """(rc, ruleset dicts). rc!=0 → LIST 자체 실패(접근불가/일시오류); 빈 리스트 반환."""
    rc, out, _ = _gh_api([f"repos/{owner}/{repo}/rulesets"])
    if rc != 0 or not out.strip():
        return rc, []
    try:
        items = json.loads(out)
    except json.JSONDecodeError:
        return rc, []
    if not isinstance(items, list):
        return rc, []
    return rc, [it for it in items if isinstance(it, dict)]


def _find_named(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for it in items:
        if it.get("name") == name:
            return it
    return None


def get_ruleset(owner: str, repo: str, name: str = RULESET_NAME) -> dict[str, Any] | None:
    rc, items = _list_rulesets(owner, repo)
    if rc != 0:
        return None
    return _find_named(items, name)


@dataclass
class ProtectResult:
    owner: str
    repo: str
    action: ProtectAction
    detail: str = ""


def apply_ruleset(
    owner: str, repo: str, *, required_reviews: int = 0, dry_run: bool = True
) -> ProtectResult:
    list_rc, items = _list_rulesets(owner, repo)
    if list_rc != 0:
        # LIST 실패 → 접근불가(probe 404) vs 일시오류 구분. POST 하지 않는다(중복 방지).
        rc, _, err = _gh_api([f"repos/{owner}/{repo}", "--jq", ".full_name"])
        if rc != 0:
            return ProtectResult(owner, repo, "no-access", err.strip()[:80])
        return ProtectResult(owner, repo, "error", "rulesets list failed")
    existing = _find_named(items, RULESET_NAME)
    payload = build_ruleset_payload(required_reviews=required_reviews)
    if existing is None:
        if dry_run:
            return ProtectResult(owner, repo, "would-create")
        rc, _, err = _gh_api(
            [f"repos/{owner}/{repo}/rulesets", "--method", "POST", "--input", "-"],
            input_str=json.dumps(payload),
        )
        return ProtectResult(owner, repo, "created" if rc == 0 else "error", err.strip()[:120])
    rid = existing.get("id")
    if rid is None:
        return ProtectResult(owner, repo, "error", "ruleset id missing in list response")
    if dry_run:
        return ProtectResult(owner, repo, "exists")
    rc, _, err = _gh_api(
        [f"repos/{owner}/{repo}/rulesets/{rid}", "--method", "PUT", "--input", "-"],
        input_str=json.dumps(payload),
    )
    return ProtectResult(owner, repo, "updated" if rc == 0 else "error", err.strip()[:120])
