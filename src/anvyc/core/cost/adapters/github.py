"""GitHub Billing adapter (CP-13 PR-13D).

ADR v6-CP-13 §4.4 / DESIGN §38.3. Enhanced Billing Platform endpoint 호출
(`GET /organizations/{org}/settings/billing/usage` 또는
`/users/{user}/settings/billing/usage`) 로 GitHub 사용 비용 합산.

설계 결정 (memory `cp13d-github-planning` Q1~Q5, 모두 Recommended):
  * Q1 endpoint = Enhanced Billing Platform (legacy `/orgs/{org}/settings/billing/{actions,packages,...}` 미사용)
  * Q2 discovery = auto-ALL (`~/.config/gh*` glob walk)
  * Q3 인증 = fine-grained PAT (Account "Plan: Read" 또는 Organization "Administration: Read")
  * Q4 측정 차원 = 모두 (breakdown dim = `product` — Enhanced billing 의 `usageItems[].product` 자연 매핑)
  * Q5 scope = 단일 PR-13D

account.key 인코딩:
  * `"<user>"`         — user-level billing (`/users/<user>/...`)
  * `"<user>@<org>"`   — org-level billing (`/organizations/<org>/...`).
                         token 은 `<user>` 의 GH_CONFIG_DIR 의 keyring 에서.

graceful skip 4 분류 (`meta.extra.error`):
  * `unauthorized`              401 → PAT 재발급 안내 (fine-grained scope)
  * `forbidden`                 403 → billing manager role 부여 안내
  * `enhanced_billing_disabled` 404 + 응답 패턴 → org admin 에 migration 요청
  * `api_error`                 5xx / 네트워크 / 기타

호출 비용 (ADR R1):
  * GitHub API 호출 자체는 무료 (rate-limit 5,000 req/h 내). 본 PR 호출
    빈도 = 일1회 × 계정 수 << limit. `meta.measurement_cost_usd = 0`.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from anvyc.core.cost.adapters.base import CostAdapterDepMissingError
from anvyc.core.cost.ledger import (
    Account,
    BreakdownItem,
    CostReport,
    CostReportMeta,
    Period,
)
from anvyc.utils.gh_hosts import (
    discover_gh_accounts,
    select_config_dir_for_user,
)

SOURCE = "github"
OPTIONAL_DEP_GROUP = "cost-github"
API_VERSION = "2026-03-10"
DEFAULT_HOST = "github.com"
ENHANCED_BILLING_TIMEOUT_SECONDS = 30.0

_log = logging.getLogger(__name__)


def _require_httpx() -> Any:
    """httpx import (lazy). 부재 시 `CostAdapterDepMissingError`."""
    try:
        import httpx  # noqa: PLC0415 — lazy import (optional dep group)
    except ImportError as e:
        raise CostAdapterDepMissingError(SOURCE, OPTIONAL_DEP_GROUP) from e
    return httpx


def _split_account_key(key: str) -> tuple[str, str | None]:
    """`"<user>"` → (user, None), `"<user>@<org>"` → (user, org)."""
    if "@" in key:
        user, _, org = key.partition("@")
        return user, org or None
    return key, None


def _gh_auth_token(config_dir: str, host: str = DEFAULT_HOST) -> str | None:
    """`gh auth token --hostname <host>` 호출로 token 추출.

    `GH_CONFIG_DIR` env 설정 → gh CLI 가 해당 dir 의 hosts.yml + keyring
    에서 token 가져옴. gh 미설치 / 인증 부재 / 호출 실패 시 `None`.
    """
    env = {**os.environ, "GH_CONFIG_DIR": config_dir}
    try:
        proc = subprocess.run(
            ["gh", "auth", "token", "--hostname", host],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    token = proc.stdout.strip()
    return token or None


def _billing_endpoint(user: str, org: str | None) -> str:
    """account.key → Enhanced Billing usage endpoint path."""
    if org:
        return f"/organizations/{org}/settings/billing/usage"
    return f"/users/{user}/settings/billing/usage"


def _classify_status(status_code: int, body: str) -> str:
    """HTTP status + body → graceful error 분류."""
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        # Enhanced billing 미활성 org 는 본 endpoint 만 404 — 정확 detection
        # 위해 body 패턴 (휴리스틱). 응답 message 가 "Enhanced billing" /
        # "not enabled" / "billing platform" 등 가능.
        lowered = body.lower()
        if "enhanced" in lowered or "billing" in lowered:
            return "enhanced_billing_disabled"
        return "not_found"
    return "api_error"


def _parse_usage_response(
    data: dict[str, Any], period: Period
) -> tuple[float, list[BreakdownItem]]:
    """Enhanced billing usage 응답 → (total, breakdown).

    응답 구조:
      { "usageItems": [
          { "date": "2026-05-01",
            "product": "Actions",
            "sku": "compute_linux",
            "quantity": 12.0,
            "unitType": "minute",
            "pricePerUnit": 0.008,
            "grossAmount": 0.096,
            "discountAmount": 0.0,
            "netAmount": 0.096,
            "organizationName": "...",
            "repositoryName": "..."
          }, ...
      ]}
    """
    items = data.get("usageItems") or []
    total = 0.0
    by_product: dict[str, float] = {}
    for item in items:
        # period 필터 — date 가 period 안에 있을 때만 합산.
        date_str = (item.get("date") or "").strip()
        if date_str and not _date_in_period(date_str, period):
            continue
        amount_raw = item.get("netAmount")
        if amount_raw is None:
            amount_raw = item.get("grossAmount") or 0
        try:
            amount = float(amount_raw)
        except (TypeError, ValueError):
            amount = 0.0
        product = (item.get("product") or "(unknown)").strip() or "(unknown)"
        by_product[product] = by_product.get(product, 0.0) + amount
        total += amount

    breakdown = [
        BreakdownItem(dim="product", key=p, amount=round(amt, 6))
        for p, amt in sorted(by_product.items(), key=lambda kv: -kv[1])
    ]
    return total, breakdown


def _date_in_period(date_str: str, period: Period) -> bool:
    """`YYYY-MM-DD` (UTC) 가 period 안인지."""
    try:
        d = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
    except ValueError:
        return True  # parse 실패 시 보수적으로 포함
    return period.start <= d < period.end


class GitHubBillingAdapter:
    """GitHub Enhanced Billing Platform adapter.

    `discover_accounts()` = `~/.config/gh*` glob 의 모든 hosts.yml 의 user.
    org-level account 는 `accounts_override` 명시 (e.g. `"heisgone@whatap"`).

    `fetch_period()` = `GH_CONFIG_DIR=<dir> gh auth token` 으로 token 추출
    후 httpx 로 Enhanced Billing usage endpoint 호출.
    """

    name = SOURCE
    optional_dep_group: str | None = OPTIONAL_DEP_GROUP

    def __init__(self, accounts_override: list[str] | None = None) -> None:
        # `accounts_override=None` 시 hosts.yml walk. test fixture 는 명시.
        self._accounts_override = accounts_override

    def discover_accounts(self) -> Iterator[Account]:
        """`~/.config/gh*` glob 의 user 들을 Account 로 yield.

        sort 순서 = key 사전식. org-level 은 override 명시 필요 (본 PR
        scope 에서는 user-level 우선 — `accounts_override` 로 확장).
        """
        if self._accounts_override is not None:
            keys = sorted(self._accounts_override)
        else:
            keys = sorted(
                {a.user for a in discover_gh_accounts()}
            )
        for key in keys:
            yield Account(source=SOURCE, key=key)

    def fetch_period(self, account: Account, period: Period) -> CostReport:
        """Enhanced billing usage 호출 → CostReport.

        graceful failure:
          * httpx 부재 → `CostAdapterDepMissingError`
          * gh 미설치 / token 부재 → amount=0 + meta.extra['error']='no_token'
          * 401 / 403 / 404 / 5xx → amount=0 + meta.extra['error']=<분류>
        """
        if account.source != SOURCE:
            raise ValueError(
                f"GitHubBillingAdapter.fetch_period: account.source != "
                f"{SOURCE!r} (got {account.source!r})"
            )

        httpx = _require_httpx()
        user, org = _split_account_key(account.key)
        config_dir = select_config_dir_for_user(user)
        if config_dir is None:
            return self._graceful_report(
                account, period, error="no_config_dir",
                detail=f"~/.config/gh* 에서 user {user!r} 의 hosts.yml 발견 실패",
            )
        token = _gh_auth_token(str(config_dir))
        if not token:
            return self._graceful_report(
                account, period, error="no_token",
                detail=f"gh auth token --hostname github.com 실패 (GH_CONFIG_DIR={config_dir})",
            )

        endpoint = _billing_endpoint(user, org)
        url = f"https://api.github.com{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        params = {
            "year": period.start.astimezone(UTC).year,
            "month": period.start.astimezone(UTC).month,
        }

        try:
            with httpx.Client(timeout=ENHANCED_BILLING_TIMEOUT_SECONDS) as client:
                resp = client.get(url, headers=headers, params=params)
        except httpx.RequestError as e:
            return self._graceful_report(
                account, period, error="api_error", detail=str(e)[:200]
            )

        if resp.status_code >= 400:
            error = _classify_status(resp.status_code, resp.text)
            return self._graceful_report(
                account, period, error=error,
                detail=f"HTTP {resp.status_code}: {resp.text[:200]}",
            )

        try:
            data = resp.json()
        except ValueError as e:
            return self._graceful_report(
                account, period, error="api_error",
                detail=f"json decode: {e}",
            )

        total, breakdown = _parse_usage_response(data, period)
        return CostReport(
            source=SOURCE,
            account=account.key,
            period=period,
            amount=round(total, 6),
            currency="USD",
            breakdown=breakdown,
            collected_at=datetime.now(UTC),
            meta=CostReportMeta(
                measurement_cost_usd=0.0,
                extra={
                    "endpoint": endpoint,
                    "scope": "org" if org else "user",
                    "item_count": len(data.get("usageItems") or []),
                },
            ),
        )

    def supports_realtime(self) -> bool:
        # Enhanced billing usage 는 일별 갱신 — MTD 실시간.
        return True

    def _graceful_report(
        self, account: Account, period: Period, *, error: str, detail: str
    ) -> CostReport:
        """401 / 403 / 404 / no_token 등 graceful skip 시 amount=0 + 표식."""
        _log.warning(
            "GitHub Billing fetch failed for account=%s error=%s detail=%s",
            account.key, error, detail,
        )
        return CostReport(
            source=SOURCE,
            account=account.key,
            period=period,
            amount=0.0,
            currency="USD",
            breakdown=[],
            collected_at=datetime.now(UTC),
            meta=CostReportMeta(
                measurement_cost_usd=0.0,
                extra={"error": error, "error_detail": detail[:200]},
            ),
        )


__all__ = [
    "API_VERSION",
    "OPTIONAL_DEP_GROUP",
    "SOURCE",
    "GitHubBillingAdapter",
]
