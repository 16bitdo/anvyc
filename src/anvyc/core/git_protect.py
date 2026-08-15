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
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Literal

RULESET_NAME = "anvyc-pr-required"

# gh 는 실패 시 stderr 에 "gh: <메시지> (HTTP NNN)" 형태로 상태를 남긴다. rc 는 401 도
# 404 도 1 이라(실측) 이 코드가 유일한 판별자다.
_HTTP_STATUS_RE = re.compile(r"\(HTTP (\d{3})\)")

GhAuthState = Literal["ok", "unauthenticated", "unavailable"]

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


def repo_admin(owner: str, repo: str) -> bool:
    """현재 gh 계정이 repo 에 admin 권한이 있는지(=ruleset 설정 가능 여부).

    404(접근불가)·admin 아님·gh 미설치 → False. ruleset 강제가 가능한 repo 만
    True 이므로, 강제 불가 repo(예: 읽기만 되는 public whatap repo)를 걸러낸다.
    """
    rc, out, _ = _gh_api([f"repos/{owner}/{repo}", "--jq", ".permissions.admin"])
    return rc == 0 and out.strip() == "true"


def repo_archived(owner: str, repo: str) -> bool:
    """repo 가 archived(read-only)인가 — ruleset 설정이 **영원히 불가능**한 상태.

    GitHub 은 archived repo 의 모든 쓰기를 403 으로 막는다. admin 권한이 있어도
    마찬가지라 `repo_admin()` 으로는 걸러지지 않는다 — 2026-08-16 실측:
    `guard protect --apply` 가 16bitdo/cc-inspect 에서
    "Repository was archived so is read-only. (HTTP 403)".

    조회 실패(404·gh 미설치·네트워크)는 False 로 뭉갠다. archived 라고 잘못 단정해
    검사를 건너뛰면 진짜 미설정을 놓치므로, 불확실할 때는 **검사하는 쪽**으로 실패한다.
    """
    rc, out, _ = _gh_api([f"repos/{owner}/{repo}", "--jq", ".archived"])
    return rc == 0 and out.strip() == "true"


def gh_auth_state() -> GhAuthState:
    """gh 로 GitHub API 를 쓸 수 있는 상태인가 — 인증 실패와 그 외를 가른다.

    `repo_admin()` 같은 per-repo 판정은 모든 실패를 False 로 뭉갠다. 그래서 토큰이
    만료되면 전 repo 가 "권한 없음" 으로 보이고, 그걸 silent 처리하는 검사는 **결과
    0건 = 문제 없음** 으로 보고한다. 2026-08-14 에 실제로 그 일이 났다 — 만료 상태에서
    doctor 가 warning=0 을 냈고, 재인증 후 같은 검사가 5건을 잡았다.

    호출자는 이 값으로 "정상" 과 "판정 불가" 를 구분해야 한다.

    401·403 → unauthenticated (재인증하면 해소)
    그 외(404 포함)·gh 부재·네트워크 → unavailable (여기서 할 수 있는 게 없다)
    """
    rc, _, err = _gh_api(["user", "--jq", ".login"])
    if rc == 0:
        return "ok"
    m = _HTTP_STATUS_RE.search(err)
    if m is not None and m.group(1) in ("401", "403"):
        return "unauthenticated"
    return "unavailable"


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
    # 적용(예정)값 가시화 — manifest defaults 상속으로 의도치 않은 값이 가는 것을
    # dry-run 단계에서 감지할 수 있게 한다 (2026-06-04 whatap count=1 오적용 재발 방지).
    info = f"required_reviews={required_reviews}"
    if existing is None:
        if dry_run:
            return ProtectResult(owner, repo, "would-create", info)
        rc, _, err = _gh_api(
            [f"repos/{owner}/{repo}/rulesets", "--method", "POST", "--input", "-"],
            input_str=json.dumps(payload),
        )
        return ProtectResult(owner, repo, "created" if rc == 0 else "error", info if rc == 0 else err.strip()[:120])
    rid = existing.get("id")
    if rid is None:
        return ProtectResult(owner, repo, "error", "ruleset id missing in list response")
    if dry_run:
        return ProtectResult(owner, repo, "exists", info)
    rc, _, err = _gh_api(
        [f"repos/{owner}/{repo}/rulesets/{rid}", "--method", "PUT", "--input", "-"],
        input_str=json.dumps(payload),
    )
    return ProtectResult(owner, repo, "updated" if rc == 0 else "error", info if rc == 0 else err.strip()[:120])
