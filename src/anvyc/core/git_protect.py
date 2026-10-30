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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

RULESET_NAME = "anvyc-pr-required"

# gh 는 실패 시 stderr 에 "gh: <메시지> (HTTP NNN)" 형태로 상태를 남긴다. rc 는 401 도
# 404 도 1 이라(실측) 이 코드가 유일한 판별자다.
_HTTP_STATUS_RE = re.compile(r"\(HTTP (\d{3})\)")

GhAuthState = Literal["ok", "unauthenticated", "unavailable"]

ProtectAction = Literal[
    "created", "updated", "exists", "would-create", "would-update", "no-access", "error"
]


# manifest merge_strategy → ruleset 의 allowed_merge_methods. 그 밖의 값은 강제하지 않는다.
MERGE_METHODS: dict[str, tuple[str, ...]] = {
    "merge": ("merge",),
    "squash": ("squash",),
    "rebase": ("rebase",),
}
# 저장소 설정(Settings → General → Pull Requests)에서 각 머지 방식을 켜는 필드
_MERGE_SETTING_FIELDS = {
    "merge": "allow_merge_commit",
    "squash": "allow_squash_merge",
    "rebase": "allow_rebase_merge",
}


def repo_merge_methods(owner: str, repo: str) -> set[str] | None:
    """저장소 설정이 허용하는 머지 방식. 조회 실패면 None.

    ruleset 의 allowed_merge_methods 와 겹치는 방식만 쓸 수 있다 — 겹치지 않으면 머지가 아예
    막힌다(GitHub 문서 「Require a pull request before merging」).
    """
    rc, out, _ = _gh_api(
        [f"repos/{owner}/{repo}", "--jq", "{allow_merge_commit, allow_squash_merge, allow_rebase_merge}"]
    )
    if rc != 0:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return {method for method, field in _MERGE_SETTING_FIELDS.items() if data.get(field) is True}


def build_ruleset_payload(
    *, required_reviews: int = 0, merge_strategy: str | None = None
) -> dict[str, Any]:
    """anvyc-pr-required 의 내용. merge_strategy 가 MERGE_METHODS 에 있으면 그 방식만 허용한다."""
    params: dict[str, Any] = {
        "required_approving_review_count": required_reviews,
        "dismiss_stale_reviews_on_push": False,
        "require_code_owner_review": False,
        "require_last_push_approval": False,
        "required_review_thread_resolution": False,
    }
    methods = MERGE_METHODS.get(merge_strategy or "")
    if methods is not None:
        params["allowed_merge_methods"] = list(methods)
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "pull_request", "parameters": params},
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


# ruleset 의 쓰기 가능한 최상위 필드(REST "Update a repository ruleset" body) 중 rules 를
# 뺀 것. GET 응답의 나머지(id · node_id · _links · 시각 등)는 조회 전용이라 PUT 과 무관하다.
_WRITABLE_TOP_KEYS = ("name", "target", "enforcement", "conditions", "bypass_actors")

# payload 가 보내지 않는 파라미터는 PUT 뒤 서버 기본값이 된다. anvyc 가 만든 ruleset 4곳
# (anvyc · okr · reflection · role-based-ruleset)을 조회해 확인한 값이다(2026-10-30).
_SERVER_DEFAULTS: dict[str, dict[str, Any]] = {
    "pull_request": {
        "required_reviewers": [],
        "require_extra_approval_for_unattributed_changes": True,
        "allowed_merge_methods": ["merge", "squash", "rebase"],
    },
}


def _canon(value: Any) -> str:
    """비교용 표현 — dict 키 순서를 무시한다(GET 응답과 payload 의 키 순서가 다르다)."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _show(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True)
class RulesetChange:
    """PUT 으로 바뀌는 것 하나.

    label 은 값 없는 짧은 이름(doctor 한 줄 요약용), line 은 값까지 담은 한 줄(guard protect 출력용).
    """

    label: str
    line: str


def _unsent_param_change(rule_type: str, key: str, before: Any) -> RulesetChange | None:
    """payload 가 보내지 않는 파라미터가 PUT 뒤 바뀌면 그 변경을, 그대로면 None 을 돌려준다.

    PUT 은 rules 를 통째로 바꾸므로 이 파라미터는 서버 기본값으로 돌아간다. 기본값을 아는
    파라미터는 값이 기본값과 다를 때만 알린다 — 손대지 않은 ruleset 에서 경고가 나면 매번
    무시하게 된다. 기본값을 모르는 파라미터(GitHub 이 새로 더한 것 등)는 바뀔 수 있다고
    알린다 — 조용히 넘기면 손으로 바꾼 값이 알림 없이 사라질 수 있다.
    """
    defaults = _SERVER_DEFAULTS.get(rule_type, {})
    name = f"{rule_type}.{key}"
    if key not in defaults:
        return RulesetChange(
            name, f"{name}: {_show(before)} → 서버 기본값(값을 모른다 — 바뀔 수 있다)"
        )
    if _canon(before) == _canon(defaults[key]):
        return None
    return RulesetChange(name, f"{name}: {_show(before)} → {_show(defaults[key])}(서버 기본값)")


def ruleset_changes(existing: dict[str, Any], payload: dict[str, Any]) -> list[RulesetChange]:
    """existing(GET rulesets/{id} 응답)을 payload 로 PUT 하면 바뀌는 것들. 같으면 빈 리스트.

    손으로 더한 규칙 · 우회 권한자 · 비상시 끈 enforcement 처럼 anvyc payload 에 없는 설정은
    PUT 이 지운다 — guard protect 는 덮어쓰기 전에, doctor 는 매일 이것을 보여 준다.
    """
    changes: list[RulesetChange] = []
    for key in _WRITABLE_TOP_KEYS:
        before, after = existing.get(key), payload.get(key)
        if _canon(before) != _canon(after):
            changes.append(RulesetChange(key, f"{key}: {_show(before)} → {_show(after)}"))

    before_rules = {
        str(r.get("type")): r.get("parameters") or {} for r in existing.get("rules") or []
    }
    after_rules = {str(r["type"]): r.get("parameters") or {} for r in payload["rules"]}
    for rtype in sorted(before_rules.keys() - after_rules.keys()):
        params = before_rules[rtype]
        line = f"규칙 삭제: {rtype}" + (f" {_show(params)}" if params else "")
        changes.append(RulesetChange(f"규칙 삭제 {rtype}", line))
    for rtype in sorted(after_rules.keys() - before_rules.keys()):
        changes.append(RulesetChange(f"규칙 추가 {rtype}", f"규칙 추가: {rtype}"))
    for rtype in sorted(before_rules.keys() & after_rules.keys()):
        before_params, after_params = before_rules[rtype], after_rules[rtype]
        for key in sorted(after_params):
            if _canon(before_params.get(key)) != _canon(after_params[key]):
                name = f"{rtype}.{key}"
                line = f"{name}: {_show(before_params.get(key))} → {_show(after_params[key])}"
                changes.append(RulesetChange(name, line))
        for key in sorted(before_params.keys() - after_params.keys()):
            change = _unsent_param_change(rtype, key, before_params[key])
            if change is not None:
                changes.append(change)
    return changes


def diff_ruleset(existing: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """ruleset_changes() 를 값까지 담은 한 줄씩으로 — guard protect 출력용."""
    return [c.line for c in ruleset_changes(existing, payload)]


def get_ruleset_detail(owner: str, repo: str, rid: Any) -> tuple[dict[str, Any] | None, str]:
    """GET rulesets/{id} → (ruleset, ""), 실패면 (None, 사유).

    LIST 응답에는 rules · bypass_actors 가 없어서 차이를 보려면 따로 읽어야 한다.
    """
    rc, out, err = _gh_api([f"repos/{owner}/{repo}/rulesets/{rid}"])
    if rc != 0:
        return None, err.strip() or f"exit {rc}"
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None, "응답이 JSON 이 아니다"
    if not isinstance(data, dict):
        return None, "응답 형식이 다르다"
    return data, ""


@dataclass
class ProtectResult:
    owner: str
    repo: str
    action: ProtectAction
    detail: str = ""
    diff: list[str] = field(default_factory=list)


def apply_ruleset(
    owner: str,
    repo: str,
    *,
    required_reviews: int = 0,
    merge_strategy: str | None = None,
    dry_run: bool = True,
    on_overwrite: Callable[[list[str]], None] | None = None,
) -> ProtectResult:
    list_rc, items = _list_rulesets(owner, repo)
    if list_rc != 0:
        # LIST 실패 → 접근불가(probe 404) vs 일시오류 구분. POST 하지 않는다(중복 방지).
        rc, _, err = _gh_api([f"repos/{owner}/{repo}", "--jq", ".full_name"])
        if rc != 0:
            return ProtectResult(owner, repo, "no-access", err.strip()[:80])
        return ProtectResult(owner, repo, "error", "rulesets list failed")
    existing = _find_named(items, RULESET_NAME)
    payload = build_ruleset_payload(
        required_reviews=required_reviews, merge_strategy=merge_strategy
    )
    # 적용(예정)값 가시화 — manifest defaults 상속으로 의도치 않은 값이 가는 것을
    # dry-run 단계에서 감지할 수 있게 한다 (2026-06-04 whatap count=1 오적용 재발 방지).
    info = f"required_reviews={required_reviews}"
    methods = MERGE_METHODS.get(merge_strategy or "")
    if methods is not None:
        shown = "/".join(methods)
        info += f" merge={shown}"
        # ruleset 이 허용할 방식을 저장소 설정이 모두 꺼 뒀으면 어떤 방식으로도 머지할 수 없다.
        # 그런 ruleset 은 만들지도 덮어쓰지도 않는다 — 설정을 못 읽어도 마찬가지다.
        allowed = repo_merge_methods(owner, repo)
        if allowed is None:
            return ProtectResult(owner, repo, "error", f"저장소 머지 설정 조회 실패 — 쓰지 않음 ({info})")
        if not set(methods) & allowed:
            return ProtectResult(
                owner,
                repo,
                "error",
                f"저장소 설정이 {shown} 머지를 꺼 둬서 이 ruleset 이면 머지가 막힌다 — 쓰지 않음"
                " (저장소 설정이나 manifest merge_strategy 를 먼저 맞춘다)",
            )
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
    detail, why = get_ruleset_detail(owner, repo, rid)
    if detail is None:
        # 기존 내용을 못 읽으면 무엇이 지워지는지 보여 줄 수 없다 — 덮어쓰지 않는다.
        return ProtectResult(
            owner, repo, "error", f"기존 ruleset 조회 실패 — 덮어쓰지 않음: {why[:80]}"
        )
    diff = diff_ruleset(detail, payload)
    if dry_run:
        return ProtectResult(owner, repo, "would-update" if diff else "exists", info, diff)
    if diff and on_overwrite is not None:
        on_overwrite(diff)  # PUT 전에 — 무엇이 바뀌는지 먼저 남긴다
    rc, _, err = _gh_api(
        [f"repos/{owner}/{repo}/rulesets/{rid}", "--method", "PUT", "--input", "-"],
        input_str=json.dumps(payload),
    )
    return ProtectResult(
        owner, repo, "updated" if rc == 0 else "error", info if rc == 0 else err.strip()[:120], diff
    )
