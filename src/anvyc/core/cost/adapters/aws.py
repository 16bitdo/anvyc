"""AWS Cost Explorer adapter (CP-13 PR-13C).

ADR v6-CP-13 §4.3 / DESIGN §38.3. boto3 의 `ce:GetCostAndUsage` 호출로
aws_profile 별 period 비용 합산. (i) 채널 = MTD 실시간 / (ii) 채널 = 동일
API + 월말 잠금 (single-API source — DESIGN §38.3 어댑터 채널 표).

graceful skip 패턴:
  * boto3 부재 → `CostAdapterDepMissingError` (`adapters/__init__.py` 의
    lazy registration 이 catch → ADAPTER_REGISTRY 에 'aws' 미등록 → doctor
    `cost-aws-explorer-iam` 이 dep_missing severity 로 안내)
  * SSO 만료 / IAM 권한 부재 → fetch_period 가 amount=0 + meta.extra
    의 `error` 키로 표식. caller (collect_reports) 는 raise 안 받음.

호출 비용 (ADR R1):
  * GetCostAndUsage 당 $0.01 → `meta.measurement_cost_usd` 에 자기 관찰
  * 14 profile × 일1회 = ~$4.20/월 (PR-13B2 cache 가 daily 1회로 제약)
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from anvyc.core.cost.adapters.base import CostAdapterDepMissingError
from anvyc.core.cost.ledger import (
    Account,
    BreakdownItem,
    CostReport,
    CostReportMeta,
    Period,
)
from anvyc.utils.aws_config import load_aws_profile_names

SOURCE = "aws"
OPTIONAL_DEP_GROUP = "cost-aws"
GET_COST_AND_USAGE_PRICE_USD = 0.01

_log = logging.getLogger(__name__)


def _require_boto3() -> Any:
    """boto3 import (lazy). 부재 시 `CostAdapterDepMissingError`."""
    try:
        import boto3  # noqa: PLC0415 — lazy import (optional dep group)
    except ImportError as e:
        raise CostAdapterDepMissingError(SOURCE, OPTIONAL_DEP_GROUP) from e
    return boto3


def _require_botocore_exceptions() -> tuple[
    type[BaseException], type[BaseException]
]:
    """botocore exception types — graceful classification 용."""
    try:
        from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415
    except ImportError as e:
        raise CostAdapterDepMissingError(SOURCE, OPTIONAL_DEP_GROUP) from e
    return BotoCoreError, ClientError


def _period_to_ce_window(period: Period) -> tuple[str, str]:
    """Period → Cost Explorer (Start, End) 'YYYY-MM-DD' 문자열.

    Cost Explorer 의 (Start, End) 는 End exclusive (anvyc Period 와 동일
    semantics). end 가 UTC 자정이 아닐 때 (예: mtd) — date 만 사용하므로
    Cost Explorer 가 자체적으로 End-1 day 까지 합산.
    """
    start = period.start.astimezone(UTC).date()
    end_dt = period.end.astimezone(UTC)
    end = end_dt.date()
    # Cost Explorer 의 End 는 exclusive; 동일 day 인 경우 +1 day 보정 (mtd 첫날).
    if end <= start:
        end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


class AwsCostExplorerAdapter:
    """AWS Cost Explorer adapter.

    `discover_accounts()` = `~/.aws/config` 의 모든 profile (auto-ALL —
    PR-13C 결정 Q1=a). SSO 만료 여부는 sts 호출 비용 회피 위해 discover 시
    검증 안 함 — fetch_period 에서 lazy 검증 (graceful skip).

    `fetch_period()` = boto3 Session(profile).client('ce').get_cost_and_usage
    호출 + Granularity=MONTHLY + GroupBy=SERVICE. 응답 ResultsByTime 의
    UnblendedCost.Amount 를 합산, Groups 로 breakdown(dim='service').
    """

    name = SOURCE
    optional_dep_group: str | None = OPTIONAL_DEP_GROUP

    def __init__(self, profiles: list[str] | None = None) -> None:
        # `profiles=None` 시 discover_accounts 가 load_aws_profile_names()
        # 호출. test fixture 는 명시.
        self._profiles_override = profiles

    def discover_accounts(self) -> Iterator[Account]:
        """`~/.aws/config` 의 모든 profile 을 Account 로 yield.

        sts 호출 없이 정적 read — SSO 만료된 profile 도 yield (fetch_period
        에서 graceful skip).
        """
        profiles = (
            sorted(self._profiles_override)
            if self._profiles_override is not None
            else sorted(load_aws_profile_names())
        )
        for profile in profiles:
            yield Account(source=SOURCE, key=profile)

    def fetch_period(self, account: Account, period: Period) -> CostReport:
        """Cost Explorer GetCostAndUsage 호출 → CostReport.

        graceful failure 패턴:
          * boto3 부재 → `CostAdapterDepMissingError` (caller catch)
          * SSO 만료 / 인증 실패 → amount=0 + meta.extra['error']='sso_expired'
          * IAM 권한 부재 → amount=0 + meta.extra['error']='access_denied'
          * 기타 ClientError / BotoCoreError → amount=0 + meta.extra['error']='api_error'
        """
        if account.source != SOURCE:
            raise ValueError(
                f"AwsCostExplorerAdapter.fetch_period: account.source != "
                f"{SOURCE!r} (got {account.source!r})"
            )

        boto3 = _require_boto3()
        botocore_error, client_error = _require_botocore_exceptions()

        start_str, end_str = _period_to_ce_window(period)

        try:
            session = boto3.Session(profile_name=account.key)
            client = session.client("ce", region_name="us-east-1")
            response = client.get_cost_and_usage(
                TimePeriod={"Start": start_str, "End": end_str},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
        except client_error as e:
            return self._graceful_report(
                account, period, error=_classify_client_error(e), exc=e
            )
        except botocore_error as e:
            # Auth / SSO / 네트워크 등 일반 오류
            return self._graceful_report(
                account, period, error=_classify_botocore_error(e), exc=e
            )

        total, breakdown = _parse_ce_response(response)
        return CostReport(
            source=SOURCE,
            account=account.key,
            period=period,
            amount=round(total, 6),
            currency="USD",
            breakdown=breakdown,
            collected_at=datetime.now(UTC),
            meta=CostReportMeta(
                measurement_cost_usd=GET_COST_AND_USAGE_PRICE_USD,
                extra={"aws_region": "us-east-1"},
            ),
        )

    def supports_realtime(self) -> bool:
        # Cost Explorer 는 (i) MTD 실시간 + (ii) 월말 잠금이 동일 API.
        return True

    def _graceful_report(
        self,
        account: Account,
        period: Period,
        *,
        error: str,
        exc: BaseException,
    ) -> CostReport:
        """SSO 만료 / IAM 부재 / API 오류 시 amount=0 + meta 에 표식.

        호출 비용 0 — 호출 자체가 실패했으므로 `measurement_cost_usd=0`.
        """
        _log.warning(
            "AWS Cost Explorer fetch failed for profile=%s error=%s exc=%s",
            account.key,
            error,
            exc,
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
                extra={"error": error, "error_detail": str(exc)[:200]},
            ),
        )


def _classify_client_error(exc: Any) -> str:
    """ClientError → error 분류 문자열.

    AccessDenied / UnrecognizedClientException → 'access_denied'
    ExpiredToken / ExpiredTokenException → 'sso_expired'
    그 외 → 'api_error'
    """
    try:
        code = exc.response.get("Error", {}).get("Code", "") or ""
    except (AttributeError, KeyError):
        code = ""
    if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
        return "access_denied"
    if code in {"ExpiredToken", "ExpiredTokenException", "InvalidIdentityToken"}:
        return "sso_expired"
    return "api_error"


def _classify_botocore_error(exc: Any) -> str:
    """BotoCoreError → error 분류 문자열 (SSO 관련 휴리스틱)."""
    msg = str(exc).lower()
    if "sso" in msg or "token has expired" in msg or "no credentials" in msg:
        return "sso_expired"
    return "api_error"


def _parse_ce_response(
    response: dict[str, Any],
) -> tuple[float, list[BreakdownItem]]:
    """Cost Explorer GetCostAndUsage 응답 → (total, breakdown).

    응답 구조 (요약):
      ResultsByTime: [
        { TimePeriod: {...}, Total: {...}, Groups: [
            { Keys: ['Amazon EC2'], Metrics: {'UnblendedCost': {'Amount': '1.23', 'Unit': 'USD'}} },
            ...
        ]}
      ]
    """
    total = 0.0
    by_service: dict[str, float] = {}
    for bucket in response.get("ResultsByTime", []) or []:
        for group in bucket.get("Groups", []) or []:
            keys = group.get("Keys") or []
            service = keys[0] if keys else "(unknown)"
            metrics = group.get("Metrics") or {}
            amount_str = (
                (metrics.get("UnblendedCost") or {}).get("Amount") or "0"
            )
            try:
                amount = float(amount_str)
            except (TypeError, ValueError):
                amount = 0.0
            by_service[service] = by_service.get(service, 0.0) + amount
            total += amount
        if not bucket.get("Groups"):
            # Group 미사용 시 Total.UnblendedCost.Amount 폴백
            metrics = bucket.get("Total") or {}
            amount_str = (
                (metrics.get("UnblendedCost") or {}).get("Amount") or "0"
            )
            with contextlib.suppress(TypeError, ValueError):
                total += float(amount_str)

    breakdown = [
        BreakdownItem(dim="service", key=svc, amount=round(amt, 6))
        for svc, amt in sorted(by_service.items(), key=lambda kv: -kv[1])
    ]
    return total, breakdown


__all__ = [
    "OPTIONAL_DEP_GROUP",
    "SOURCE",
    "AwsCostExplorerAdapter",
]
