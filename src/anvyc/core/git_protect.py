# src/anvyc/core/git_protect.py
"""GitHub repository ruleset 으로 서버측 PR 강제를 적용한다.

`anvyc guard protect` 가 활성 gh 계정으로 대상 repo 에 `anvyc-pr-required`
ruleset 을 생성/갱신한다. 직접 push 는 pull_request 규칙으로 차단된다.
접근 불가(whatap 등 404)는 no-access 로 분류해 silent 처리한다.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any

RULESET_NAME = "anvyc-pr-required"


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
    args: list[str],
    *,
    input_str: str | None = None,
    timeout: int = 20,
) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["gh", "api", *args],
            input=input_str,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return 127, "", "gh CLI not found"
    except subprocess.SubprocessError as e:
        return 1, "", str(e)
    return proc.returncode, proc.stdout, proc.stderr


def get_ruleset(
    owner: str,
    repo: str,
    name: str = RULESET_NAME,
) -> dict[str, Any] | None:
    rc, out, _ = _gh_api([f"repos/{owner}/{repo}/rulesets"])
    if rc != 0 or not out.strip():
        return None
    try:
        items = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not isinstance(items, list):
        return None
    for it in items:
        if isinstance(it, dict) and it.get("name") == name:
            return it
    return None


@dataclass
class ProtectResult:
    owner: str
    repo: str
    action: str  # created|updated|exists|would-create|would-update|no-access|error
    detail: str = field(default="")


def apply_ruleset(
    owner: str,
    repo: str,
    *,
    required_reviews: int = 0,
    dry_run: bool = True,
) -> ProtectResult:
    existing = get_ruleset(owner, repo)
    payload = build_ruleset_payload(required_reviews=required_reviews)

    if existing is None:
        rc, _, err = _gh_api([f"repos/{owner}/{repo}", "--jq", ".full_name"])
        if rc != 0:
            return ProtectResult(owner, repo, "no-access", err.strip()[:80])
        if dry_run:
            return ProtectResult(owner, repo, "would-create")
        rc, _, err = _gh_api(
            [f"repos/{owner}/{repo}/rulesets", "--method", "POST", "--input", "-"],
            input_str=json.dumps(payload),
        )
        return ProtectResult(owner, repo, "created" if rc == 0 else "error", err.strip()[:120])

    if dry_run:
        return ProtectResult(owner, repo, "exists")

    rid = existing.get("id")
    rc, _, err = _gh_api(
        [f"repos/{owner}/{repo}/rulesets/{rid}", "--method", "PUT", "--input", "-"],
        input_str=json.dumps(payload),
    )
    return ProtectResult(owner, repo, "updated" if rc == 0 else "error", err.strip()[:120])
