"""Unit tests for anvyc.core.cost.adapters.aws (CP-13 PR-13C).

mock 전략 (PR-13C 결정 Q4=a): `unittest.mock.patch` 로 boto3.Session 을
교체. moto 미사용 — anvyc 기존 dev dep 보존.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from anvyc.core.cost.adapters.aws import (
    GET_COST_AND_USAGE_PRICE_USD,
    OPTIONAL_DEP_GROUP,
    SOURCE,
    AwsCostExplorerAdapter,
    _classify_botocore_error,
    _classify_client_error,
    _parse_ce_response,
    _period_to_ce_window,
)
from anvyc.core.cost.adapters.base import CostAdapterDepMissingError
from anvyc.core.cost.ledger import Account, Period

# ---------------------------------------------------------------------------
# pure helpers (no mocks)
# ---------------------------------------------------------------------------


def test_source_and_optional_dep_group() -> None:
    assert SOURCE == "aws"
    assert OPTIONAL_DEP_GROUP == "cost-aws"


def test_period_to_ce_window_full_month() -> None:
    p = Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )
    assert _period_to_ce_window(p) == ("2026-05-01", "2026-06-01")


def test_period_to_ce_window_mtd_first_day_boundary() -> None:
    """mtd 첫날 (start = end.date()) 시 End +1day 보정."""
    p = Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 5, 1, 3, 0, tzinfo=UTC),
    )
    s, e = _period_to_ce_window(p)
    assert s == "2026-05-01"
    assert e == "2026-05-02"


def test_parse_ce_response_groups() -> None:
    response = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-05-01", "End": "2026-06-01"},
                "Groups": [
                    {
                        "Keys": ["Amazon EC2"],
                        "Metrics": {
                            "UnblendedCost": {"Amount": "12.34", "Unit": "USD"}
                        },
                    },
                    {
                        "Keys": ["AmazonCloudWatch"],
                        "Metrics": {
                            "UnblendedCost": {"Amount": "1.50", "Unit": "USD"}
                        },
                    },
                ],
            }
        ]
    }
    total, breakdown = _parse_ce_response(response)
    assert total == pytest.approx(13.84)
    assert [b.key for b in breakdown] == ["Amazon EC2", "AmazonCloudWatch"]
    assert all(b.dim == "service" for b in breakdown)


def test_parse_ce_response_no_groups_falls_back_to_total() -> None:
    response = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-05-01", "End": "2026-06-01"},
                "Total": {"UnblendedCost": {"Amount": "5.00", "Unit": "USD"}},
                "Groups": [],
            }
        ]
    }
    total, breakdown = _parse_ce_response(response)
    assert total == pytest.approx(5.0)
    assert breakdown == []


def test_parse_ce_response_bad_amount_graceful() -> None:
    response = {
        "ResultsByTime": [
            {
                "Groups": [
                    {
                        "Keys": ["X"],
                        "Metrics": {"UnblendedCost": {"Amount": "not-a-number"}},
                    }
                ]
            }
        ]
    }
    total, _ = _parse_ce_response(response)
    assert total == pytest.approx(0.0)


def test_classify_client_error_access_denied() -> None:
    exc = MagicMock()
    exc.response = {"Error": {"Code": "AccessDenied"}}
    assert _classify_client_error(exc) == "access_denied"


def test_classify_client_error_expired_token() -> None:
    exc = MagicMock()
    exc.response = {"Error": {"Code": "ExpiredTokenException"}}
    assert _classify_client_error(exc) == "sso_expired"


def test_classify_client_error_unknown() -> None:
    exc = MagicMock()
    exc.response = {"Error": {"Code": "SomeOther"}}
    assert _classify_client_error(exc) == "api_error"


def test_classify_botocore_error_sso() -> None:
    class _FakeError(Exception):
        pass

    assert _classify_botocore_error(_FakeError("SSO Token has expired")) == "sso_expired"
    assert _classify_botocore_error(_FakeError("connection reset")) == "api_error"


# ---------------------------------------------------------------------------
# discover_accounts
# ---------------------------------------------------------------------------


def test_discover_accounts_uses_aws_config_when_no_override() -> None:
    profiles = {"ws-dev", "ws-mgmt", "whatap-dev"}
    with patch(
        "anvyc.core.cost.adapters.aws.load_aws_profile_names",
        return_value=profiles,
    ):
        adapter = AwsCostExplorerAdapter()
        accounts = list(adapter.discover_accounts())
    assert [a.source for a in accounts] == ["aws"] * 3
    assert sorted(a.key for a in accounts) == sorted(profiles)


def test_discover_accounts_override_takes_precedence() -> None:
    adapter = AwsCostExplorerAdapter(profiles=["p1", "p2"])
    accounts = list(adapter.discover_accounts())
    assert [a.key for a in accounts] == ["p1", "p2"]


def test_discover_accounts_empty_config_yields_nothing() -> None:
    with patch(
        "anvyc.core.cost.adapters.aws.load_aws_profile_names",
        return_value=set(),
    ):
        adapter = AwsCostExplorerAdapter()
        assert list(adapter.discover_accounts()) == []


# ---------------------------------------------------------------------------
# fetch_period — boto3 mock
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_boto3_session() -> tuple[MagicMock, MagicMock]:
    """boto3.Session 과 그 client('ce').get_cost_and_usage 를 mock 반환."""
    session = MagicMock(name="boto3.Session")
    ce_client = MagicMock(name="ce client")
    session.return_value.client.return_value = ce_client
    return session, ce_client


def _ce_response(amount: str = "100.00") -> dict[str, Any]:
    return {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-05-01", "End": "2026-06-01"},
                "Groups": [
                    {
                        "Keys": ["Amazon EC2"],
                        "Metrics": {
                            "UnblendedCost": {"Amount": amount, "Unit": "USD"}
                        },
                    }
                ],
            }
        ]
    }


def test_fetch_period_happy_path(fake_boto3_session: tuple[MagicMock, MagicMock]) -> None:
    session_cls, ce_client = fake_boto3_session
    ce_client.get_cost_and_usage.return_value = _ce_response("100.00")

    fake_boto3 = MagicMock()
    fake_boto3.Session = session_cls

    adapter = AwsCostExplorerAdapter(profiles=["ws-dev"])
    with patch(
        "anvyc.core.cost.adapters.aws._require_boto3",
        return_value=fake_boto3,
    ), patch(
        "anvyc.core.cost.adapters.aws._require_botocore_exceptions",
        return_value=(RuntimeError, ValueError),  # mock — won't be raised
    ):
        report = adapter.fetch_period(
            Account(source="aws", key="ws-dev"),
            Period(
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 6, 1, tzinfo=UTC),
            ),
        )

    assert report.source == "aws"
    assert report.account == "ws-dev"
    assert report.amount == pytest.approx(100.0)
    assert report.currency == "USD"
    assert len(report.breakdown) == 1
    assert report.breakdown[0].dim == "service"
    assert report.breakdown[0].key == "Amazon EC2"
    assert report.meta.measurement_cost_usd == pytest.approx(
        GET_COST_AND_USAGE_PRICE_USD
    )
    # boto3 호출 인자 검증
    session_cls.assert_called_once_with(profile_name="ws-dev")
    ce_client.get_cost_and_usage.assert_called_once()
    call_kwargs = ce_client.get_cost_and_usage.call_args.kwargs
    assert call_kwargs["TimePeriod"] == {
        "Start": "2026-05-01",
        "End": "2026-06-01",
    }
    assert call_kwargs["Granularity"] == "MONTHLY"
    assert call_kwargs["Metrics"] == ["UnblendedCost"]


def test_fetch_period_sso_expired_graceful() -> None:
    """ClientError(Code=ExpiredTokenException) → amount=0 + meta.error='sso_expired'."""

    class FakeClientError(Exception):
        def __init__(self) -> None:
            super().__init__("token expired")
            self.response = {"Error": {"Code": "ExpiredTokenException"}}

    class FakeBotoCoreError(Exception):
        pass

    fake_boto3 = MagicMock()
    session = MagicMock()
    session.return_value.client.return_value.get_cost_and_usage.side_effect = (
        FakeClientError()
    )
    fake_boto3.Session = session

    adapter = AwsCostExplorerAdapter(profiles=["ws-dev"])
    with patch(
        "anvyc.core.cost.adapters.aws._require_boto3",
        return_value=fake_boto3,
    ), patch(
        "anvyc.core.cost.adapters.aws._require_botocore_exceptions",
        return_value=(FakeBotoCoreError, FakeClientError),
    ):
        report = adapter.fetch_period(
            Account(source="aws", key="ws-dev"),
            Period(
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 6, 1, tzinfo=UTC),
            ),
        )

    assert report.amount == 0.0
    assert report.meta.measurement_cost_usd == 0.0
    assert report.meta.extra.get("error") == "sso_expired"


def test_fetch_period_access_denied_graceful() -> None:
    class FakeClientError(Exception):
        def __init__(self) -> None:
            super().__init__("access denied")
            self.response = {"Error": {"Code": "AccessDenied"}}

    class FakeBotoCoreError(Exception):
        pass

    fake_boto3 = MagicMock()
    fake_boto3.Session.return_value.client.return_value.get_cost_and_usage.side_effect = (
        FakeClientError()
    )

    adapter = AwsCostExplorerAdapter(profiles=["ws-dev"])
    with patch(
        "anvyc.core.cost.adapters.aws._require_boto3",
        return_value=fake_boto3,
    ), patch(
        "anvyc.core.cost.adapters.aws._require_botocore_exceptions",
        return_value=(FakeBotoCoreError, FakeClientError),
    ):
        report = adapter.fetch_period(
            Account(source="aws", key="ws-dev"),
            Period(
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 6, 1, tzinfo=UTC),
            ),
        )

    assert report.amount == 0.0
    assert report.meta.extra.get("error") == "access_denied"


def test_fetch_period_wrong_source_raises() -> None:
    adapter = AwsCostExplorerAdapter(profiles=["x"])
    with pytest.raises(ValueError, match="account.source"):
        adapter.fetch_period(
            Account(source="anthropic", key="x"),
            Period(
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 6, 1, tzinfo=UTC),
            ),
        )


def test_supports_realtime() -> None:
    assert AwsCostExplorerAdapter().supports_realtime() is True


def test_require_boto3_raises_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """boto3 import 실패 시뮬레이션 — CostAdapterDepMissingError."""
    import builtins

    import anvyc.core.cost.adapters.aws as aws_mod

    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "boto3":
            raise ImportError("no module 'boto3'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(CostAdapterDepMissingError) as exc_info:
        aws_mod._require_boto3()
    assert exc_info.value.source == "aws"
    assert exc_info.value.group == "cost-aws"


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_registry_includes_aws_when_boto3_available() -> None:
    """`importlib.util.find_spec('boto3')` 가 None 아니면 registry 에 'aws' 등록."""
    import importlib.util

    if importlib.util.find_spec("boto3") is None:
        pytest.skip("boto3 not installed — registry skip path covered by other test")
    from anvyc.core.cost.adapters import ADAPTER_REGISTRY

    assert "aws" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["aws"].name == "aws"


def test_build_registry_excludes_aws_when_boto3_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """find_spec 가 None 일 때 _build_registry() → 'aws' 미포함."""
    import importlib.util as iutil

    original_find_spec = iutil.find_spec

    def _fake_find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "boto3":
            return None
        return original_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(iutil, "find_spec", _fake_find_spec)
    from anvyc.core.cost.adapters import _build_registry  # noqa: PLC0415

    registry = _build_registry()
    assert "aws" not in registry
    assert "anthropic" in registry
