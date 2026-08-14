"""cost-github-pat-scope check — CP-13 PR-13D.

DESIGN §38.6 의 5종 cost check 중 하나. `~/.config/gh*` 의 각 user 토큰이
Enhanced Billing user endpoint 호출 가능 권한 (OAuth/classic `user` scope
또는 fine-grained "Plan: Read") 보유 여부 검증.

`manage_billing:*` 은 enterprise / Copilot 전용이라 개인 user billing 에는
해당하지 않는다. 실제 요구 scope 은 GitHub 공식 문서에 기재돼 있지 않고
응답 헤더 `X-Accepted-Oauth-Scopes: user` 로만 확인된다 (#192).

severity:
  * httpx 미설치 → WARNING (graceful skip — `pip install 'anvyc[cost-github]'`)
  * gh CLI 미설치 → INFO (silent — 사용자가 gh 미사용)
  * hosts.yml 자체 부재 → result 없음 (silent)
  * 권한 OK (HTTP 200) → result 없음 (silent — noise 최소화)
  * HTTP 401 → WARNING + PAT 재발급 안내
  * HTTP 403 → INFO + billing manager role 안내
  * HTTP 404 → INFO — 응답 헤더(`X-Accepted-OAuth-Scopes`)로 scope 부족과
    Enhanced billing 미활성을 구분해 안내
  * 네트워크 오류 → INFO + 메시지

본 check 는 외부 호출 (1 req per user per doctor run) 동반 — 일1회 doctor
가정 시 rate-limit 무관. `anvyc doctor --skip cost-github-pat-scope` 로
회피 가능.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import subprocess
from datetime import UTC, datetime

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.utils.gh_hosts import (
    discover_gh_accounts,
    select_config_dir_for_user,
)

CHECK_NAME = "cost-github-pat-scope"
API_VERSION = "2026-03-10"
HOST_DEFAULT = "github.com"
TIMEOUT_SECONDS = 15.0

_log = logging.getLogger(__name__)


def _httpx_available() -> bool:
    return importlib.util.find_spec("httpx") is not None


def _gh_auth_token(
    config_dir: str, host: str = HOST_DEFAULT, user: str | None = None
) -> str | None:
    env = {**os.environ, "GH_CONFIG_DIR": config_dir}
    cmd = ["gh", "auth", "token", "--hostname", host]
    if user:
        # --user 를 빼면 active account 의 토큰이 반환돼, user 를 순회해도
        # 실제로는 같은 토큰 하나로 검증하게 된다 (#192 ①).
        cmd += ["--user", user]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, env=env,
            check=False, timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _header(headers: dict[str, str], name: str) -> str:
    """대소문자 무시 헤더 조회 (httpx Headers / plain dict 모두 허용)."""
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return str(value)
    return ""


def _missing_scopes(accepted: str, current: str) -> list[str]:
    """`X-Accepted-OAuth-Scopes` 를 하나도 보유하지 않으면 부족 목록 반환.

    GitHub 은 accepted 목록 중 **하나만** 있어도 통과시키므로 교집합이 빌
    때만 부족으로 본다. accepted 가 비어 있으면 판정 근거가 없어 빈 목록.
    """
    accepted_set = {s.strip() for s in accepted.split(",") if s.strip()}
    if not accepted_set:
        return []
    current_set = {s.strip() for s in current.split(",") if s.strip()}
    if accepted_set & current_set:
        return []
    return sorted(accepted_set)


def _error_message(body: str) -> str:
    """응답 body 에서 `message` 필드만 추출.

    body 전체로 문자열 매칭하면 `documentation_url` 의 `/rest/billing/` 이
    항상 걸려 원인 불문 오진한다 (#192 ③). JSON 이 아니면 body 를 그대로 쓴다.
    """
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return body
    if isinstance(parsed, dict):
        return str(parsed.get("message") or "")
    return body


class CostGithubPatScopeCheck:
    """fine-grained PAT 의 billing scope 검증."""

    name = CHECK_NAME

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        if not _httpx_available():
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=(
                        "GitHub Billing adapter 비활성 — httpx 미설치 "
                        "(cost-github optional dep)"
                    ),
                    suggestion=(
                        # --user 미사용 (venv 안에서 실패) — pipx/uv/brew/venv 어디서든
                        # 복붙 가능하도록 plain install. cost_aws_explorer_iam 와 동일.
                        "pip install 'anvyc[cost-github]' "
                        "(설치 후 `anvyc cost collect --source github` 가능)"
                    ),
                )
            ]

        accounts = discover_gh_accounts()
        if not accounts:
            return []  # hosts.yml 자체 부재 — silent

        # user 별로 한 번만 검증 (config_dir 중복 회피)
        seen_users: set[str] = set()
        results: list[CheckResult] = []
        for acct in accounts:
            if acct.user in seen_users:
                continue
            seen_users.add(acct.user)
            # 사전식 첫 dir 이 아니라 `gh-<user>` 우선 정책을 따른다 (#192 ②).
            # select 가 None 이면 발견 시점의 dir 로 fallback.
            cfg_dir = select_config_dir_for_user(acct.user) or acct.config_dir
            results.extend(
                self._check_user(acct.user, str(cfg_dir), acct.host)
            )
        return results

    def _check_user(
        self, user: str, config_dir: str, host: str
    ) -> list[CheckResult]:
        token = _gh_auth_token(config_dir, host=host, user=user)
        if not token:
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"user {user!r}: gh CLI 의 token 가져오기 실패 — "
                        f"billing 권한 검증 보류"
                    ),
                    suggestion=(
                        f"GH_CONFIG_DIR={config_dir} gh auth status "
                        f"(또는 `gh auth login --with-token`)"
                    ),
                )
            ]

        import httpx  # noqa: PLC0415 — _httpx_available 통과 후

        url = f"https://api.{host}/users/{user}/settings/billing/usage"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        now = datetime.now(UTC)
        params = {"year": now.year, "month": now.month}

        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                resp = client.get(url, headers=headers, params=params)
        except httpx.RequestError as e:
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"user {user!r}: 네트워크 오류 — 권한 검증 보류"
                    ),
                    suggestion=str(e)[:200],
                )
            ]

        return self._classify(
            user, resp.status_code, resp.text, dict(resp.headers)
        )

    def _classify(
        self,
        user: str,
        status: int,
        body: str,
        headers: dict[str, str] | None = None,
    ) -> list[CheckResult]:
        if status < 400:
            return []  # OK — silent
        if status == 401:
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=(
                        f"user {user!r}: PAT 가 billing 권한 부재 (HTTP 401)"
                    ),
                    suggestion=(
                        # 최소 해법은 PAT 신규 발급이 아니라 기존 토큰에 scope
                        # 추가다. billing endpoint 는 응답 헤더
                        # `X-Accepted-Oauth-Scopes: user` 로 이를 알린다.
                        "gh auth refresh -h github.com -s user "
                        "(기존 토큰에 scope 추가 — PAT 발급 불필요). "
                        "대안: fine-grained PAT — Resource owner=본인, "
                        "Account permissions: Plan: Read-only "
                        "(https://github.com/settings/personal-access-tokens/new)"
                    ),
                )
            ]
        if status == 403:
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"user {user!r}: billing 권한 거부 (HTTP 403) — "
                        f"개인 billing 페이지 접근 불가능한 계정 유형"
                    ),
                    suggestion=(
                        "user-level billing 은 본인 계정만 — 다른 user PAT "
                        "는 본인 user-level billing 만 호출 가능"
                    ),
                )
            ]
        if status == 404:
            # GitHub 은 scope 부족을 403 이 아니라 404 로 응답한다. 판정 근거는
            # body 가 아니라 헤더다 (#192 ③) — gh CLI 도 같은 헤더를 읽는다.
            missing = _missing_scopes(
                _header(headers or {}, "X-Accepted-OAuth-Scopes"),
                _header(headers or {}, "X-OAuth-Scopes"),
            )
            if missing:
                return [
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.INFO,
                        message=(
                            f"user {user!r}: billing endpoint 가 요구하는 "
                            f"scope 부재 — {', '.join(missing)} (HTTP 404)"
                        ),
                        suggestion=(
                            f"gh auth refresh -h github.com -s {missing[0]} "
                            "(기존 토큰에 scope 추가 — PAT 발급 불필요)"
                        ),
                    )
                ]
            lowered = _error_message(body).lower()
            if "enhanced" in lowered or "billing" in lowered:
                return [
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.INFO,
                        message=(
                            f"user {user!r}: Enhanced Billing Platform 미활성 "
                            f"(HTTP 404)"
                        ),
                        suggestion=(
                            "https://docs.github.com/en/billing/managing-your-billing/"
                            "about-the-enhanced-billing-platform 참조 — "
                            "본인 계정의 billing settings 에서 migration"
                        ),
                    )
                ]
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"user {user!r}: billing endpoint 404 — 본 user 계정 "
                        f"부재 또는 endpoint 변경"
                    ),
                )
            ]
        return [
            CheckResult(
                check_name=self.name,
                severity=Severity.INFO,
                message=(
                    f"user {user!r}: billing endpoint HTTP {status} — 권한 "
                    f"검증 보류"
                ),
                suggestion=body[:200],
            )
        ]
