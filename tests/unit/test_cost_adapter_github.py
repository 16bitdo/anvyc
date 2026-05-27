"""GitHub Billing adapter 단위 테스트 (CP-13 PR-13D).

mock 전략 (PR-13D 결정 Q4=a 미러): unittest.mock.patch 로 httpx Client 및
gh subprocess 교체. 외부 호출 0.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from anvyc.core.cost.adapters.base import CostAdapterDepMissingError
from anvyc.core.cost.adapters.github import (
    API_VERSION,
    OPTIONAL_DEP_GROUP,
    SOURCE,
    GitHubBillingAdapter,
    _billing_endpoint,
    _classify_status,
    _date_in_period,
    _parse_usage_response,
    _split_account_key,
)
from anvyc.core.cost.ledger import Account, Period

# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_source_and_optional_dep_group() -> None:
    assert SOURCE == "github"
    assert OPTIONAL_DEP_GROUP == "cost-github"
    assert API_VERSION == "2026-03-10"


def test_split_account_key_user_only() -> None:
    assert _split_account_key("16bitdo") == ("16bitdo", None)


def test_split_account_key_user_at_org() -> None:
    assert _split_account_key("heisgone@whatap") == ("heisgone", "whatap")


def test_split_account_key_empty_org_treated_as_none() -> None:
    assert _split_account_key("u@") == ("u", None)


def test_billing_endpoint_user() -> None:
    assert (
        _billing_endpoint("16bitdo", None)
        == "/users/16bitdo/settings/billing/usage"
    )


def test_billing_endpoint_org() -> None:
    assert (
        _billing_endpoint("heisgone", "whatap")
        == "/organizations/whatap/settings/billing/usage"
    )


def test_classify_status_401() -> None:
    assert _classify_status(401, "") == "unauthorized"


def test_classify_status_403() -> None:
    assert _classify_status(403, "") == "forbidden"


def test_classify_status_404_enhanced_disabled() -> None:
    assert (
        _classify_status(404, "Enhanced billing not enabled")
        == "enhanced_billing_disabled"
    )


def test_classify_status_404_unrelated_text() -> None:
    """billing/enhanced 키워드 없음 → not_found."""
    assert _classify_status(404, "random other text") == "not_found"


def test_classify_status_404_billing_keyword() -> None:
    """body 에 'billing' 만 있어도 enhanced 로 분류 (보수적)."""
    assert (
        _classify_status(404, "Account not on the new billing platform")
        == "enhanced_billing_disabled"
    )


def test_classify_status_500() -> None:
    assert _classify_status(500, "") == "api_error"


def test_date_in_period_inside() -> None:
    period = Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )
    assert _date_in_period("2026-05-15", period) is True


def test_date_in_period_outside() -> None:
    period = Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )
    assert _date_in_period("2026-06-15", period) is False


def test_date_in_period_invalid_date_kept() -> None:
    period = Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )
    # 보수적으로 포함 — parse 실패 시 True
    assert _date_in_period("bogus", period) is True


def test_parse_usage_response_groups_by_product() -> None:
    period = Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )
    data: dict[str, Any] = {
        "usageItems": [
            {"date": "2026-05-01", "product": "Actions", "netAmount": 1.0},
            {"date": "2026-05-15", "product": "Actions", "netAmount": 2.5},
            {"date": "2026-05-20", "product": "Storage", "netAmount": 0.5},
            {"date": "2026-06-15", "product": "Actions", "netAmount": 99.0},
        ]
    }
    total, breakdown = _parse_usage_response(data, period)
    assert total == pytest.approx(4.0)
    assert {b.key: b.amount for b in breakdown} == {
        "Actions": pytest.approx(3.5),
        "Storage": pytest.approx(0.5),
    }
    assert breakdown[0].key == "Actions"  # 큰 amount 먼저
    assert all(b.dim == "product" for b in breakdown)


def test_parse_usage_response_falls_back_to_gross() -> None:
    period = Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )
    data: dict[str, Any] = {
        "usageItems": [
            {"date": "2026-05-01", "product": "X", "grossAmount": 7.0},
        ]
    }
    total, _ = _parse_usage_response(data, period)
    assert total == pytest.approx(7.0)


def test_parse_usage_response_empty() -> None:
    period = Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )
    total, breakdown = _parse_usage_response({}, period)
    assert total == 0.0
    assert breakdown == []


# ---------------------------------------------------------------------------
# discover_accounts
# ---------------------------------------------------------------------------


def test_discover_accounts_override() -> None:
    adapter = GitHubBillingAdapter(accounts_override=["16bitdo", "heisgone@whatap"])
    keys = sorted(a.key for a in adapter.discover_accounts())
    assert keys == ["16bitdo", "heisgone@whatap"]


def test_discover_accounts_from_hosts_yml(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = [
        MagicMock(user="16bitdo"),
        MagicMock(user="heisgone"),
        MagicMock(user="16bitdo"),  # 중복 — discover 가 dedup
    ]
    monkeypatch.setattr(
        "anvyc.core.cost.adapters.github.discover_gh_accounts",
        lambda: fake,
    )
    adapter = GitHubBillingAdapter()
    keys = sorted(a.key for a in adapter.discover_accounts())
    assert keys == ["16bitdo", "heisgone"]


# ---------------------------------------------------------------------------
# fetch_period — httpx mock
# ---------------------------------------------------------------------------


def _make_fake_httpx(response_status: int, response_json: Any = None,
                     response_text: str = "") -> MagicMock:
    """Mocked httpx module with Client returning controlled response."""
    fake_httpx = MagicMock()

    response = MagicMock()
    response.status_code = response_status
    response.text = response_text
    if response_json is not None:
        response.json.return_value = response_json
    else:
        response.json.side_effect = ValueError("not json")

    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.return_value = response

    fake_httpx.Client.return_value = client

    # RequestError 는 실제 raise 대상 type — 임의 Exception class
    fake_httpx.RequestError = type("FakeRequestError", (Exception,), {})
    return fake_httpx


def _patch_token(token: str | None = "ghp_fake") -> Any:
    return patch(
        "anvyc.core.cost.adapters.github._gh_auth_token",
        return_value=token,
    )


def _patch_config_dir(path: str = "/tmp/gh-fake") -> Any:
    from pathlib import Path

    return patch(
        "anvyc.core.cost.adapters.github.select_config_dir_for_user",
        return_value=Path(path),
    )


def _patch_httpx(fake_httpx: MagicMock) -> Any:
    return patch(
        "anvyc.core.cost.adapters.github._require_httpx",
        return_value=fake_httpx,
    )


def _may_period() -> Period:
    return Period(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )


def test_fetch_period_happy_path_user_level() -> None:
    fake_httpx = _make_fake_httpx(
        200,
        {
            "usageItems": [
                {"date": "2026-05-10", "product": "Actions", "netAmount": 12.0},
                {"date": "2026-05-20", "product": "Packages", "netAmount": 3.5},
            ]
        },
    )
    adapter = GitHubBillingAdapter(accounts_override=["16bitdo"])

    with _patch_httpx(fake_httpx), _patch_config_dir(), _patch_token():
        report = adapter.fetch_period(
            Account(source="github", key="16bitdo"), _may_period()
        )

    assert report.source == "github"
    assert report.account == "16bitdo"
    assert report.amount == pytest.approx(15.5)
    assert report.currency == "USD"
    assert {b.key for b in report.breakdown} == {"Actions", "Packages"}
    assert report.meta.measurement_cost_usd == 0.0
    assert report.meta.extra["scope"] == "user"
    assert report.meta.extra["item_count"] == 2

    # httpx 호출 검증
    client = fake_httpx.Client.return_value
    call_kwargs = client.get.call_args
    assert "/users/16bitdo/settings/billing/usage" in call_kwargs.args[0]
    headers = call_kwargs.kwargs["headers"]
    assert headers["Authorization"] == "Bearer ghp_fake"
    assert headers["X-GitHub-Api-Version"] == API_VERSION
    assert call_kwargs.kwargs["params"]["year"] == 2026
    assert call_kwargs.kwargs["params"]["month"] == 5


def test_fetch_period_org_level_endpoint() -> None:
    fake_httpx = _make_fake_httpx(200, {"usageItems": []})
    adapter = GitHubBillingAdapter(accounts_override=["heisgone@whatap"])

    with _patch_httpx(fake_httpx), _patch_config_dir(), _patch_token():
        report = adapter.fetch_period(
            Account(source="github", key="heisgone@whatap"), _may_period()
        )

    assert report.amount == 0.0
    assert report.meta.extra["scope"] == "org"

    client = fake_httpx.Client.return_value
    url = client.get.call_args.args[0]
    assert "/organizations/whatap/settings/billing/usage" in url


def test_fetch_period_401_unauthorized() -> None:
    fake_httpx = _make_fake_httpx(401, response_text="Bad credentials")
    adapter = GitHubBillingAdapter(accounts_override=["16bitdo"])

    with _patch_httpx(fake_httpx), _patch_config_dir(), _patch_token():
        report = adapter.fetch_period(
            Account(source="github", key="16bitdo"), _may_period()
        )

    assert report.amount == 0.0
    assert report.meta.extra["error"] == "unauthorized"


def test_fetch_period_403_forbidden() -> None:
    fake_httpx = _make_fake_httpx(403, response_text="Forbidden")
    adapter = GitHubBillingAdapter(accounts_override=["16bitdo"])
    with _patch_httpx(fake_httpx), _patch_config_dir(), _patch_token():
        report = adapter.fetch_period(
            Account(source="github", key="16bitdo"), _may_period()
        )
    assert report.meta.extra["error"] == "forbidden"


def test_fetch_period_404_enhanced_disabled() -> None:
    fake_httpx = _make_fake_httpx(
        404, response_text="Enhanced billing platform not enabled"
    )
    adapter = GitHubBillingAdapter(accounts_override=["heisgone@whatap"])
    with _patch_httpx(fake_httpx), _patch_config_dir(), _patch_token():
        report = adapter.fetch_period(
            Account(source="github", key="heisgone@whatap"), _may_period()
        )
    assert report.meta.extra["error"] == "enhanced_billing_disabled"


def test_fetch_period_network_error() -> None:
    fake_httpx = MagicMock()
    fake_httpx.RequestError = type("FakeRequestError", (Exception,), {})

    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.side_effect = fake_httpx.RequestError("connection reset")
    fake_httpx.Client.return_value = client

    adapter = GitHubBillingAdapter(accounts_override=["16bitdo"])
    with _patch_httpx(fake_httpx), _patch_config_dir(), _patch_token():
        report = adapter.fetch_period(
            Account(source="github", key="16bitdo"), _may_period()
        )
    assert report.meta.extra["error"] == "api_error"


def test_fetch_period_no_token() -> None:
    fake_httpx = _make_fake_httpx(200, {"usageItems": []})
    adapter = GitHubBillingAdapter(accounts_override=["16bitdo"])
    with _patch_httpx(fake_httpx), _patch_config_dir(), _patch_token(token=None):
        report = adapter.fetch_period(
            Account(source="github", key="16bitdo"), _may_period()
        )
    assert report.meta.extra["error"] == "no_token"


def test_fetch_period_no_config_dir() -> None:
    fake_httpx = _make_fake_httpx(200, {"usageItems": []})
    adapter = GitHubBillingAdapter(accounts_override=["unknown"])
    with _patch_httpx(fake_httpx), patch(
        "anvyc.core.cost.adapters.github.select_config_dir_for_user",
        return_value=None,
    ):
        report = adapter.fetch_period(
            Account(source="github", key="unknown"), _may_period()
        )
    assert report.meta.extra["error"] == "no_config_dir"


def test_fetch_period_wrong_source_raises() -> None:
    adapter = GitHubBillingAdapter(accounts_override=["x"])
    with pytest.raises(ValueError, match="account.source"):
        adapter.fetch_period(
            Account(source="aws", key="x"), _may_period()
        )


def test_supports_realtime() -> None:
    assert GitHubBillingAdapter().supports_realtime() is True


def test_require_httpx_raises_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """httpx import 실패 시 CostAdapterDepMissingError."""
    import builtins

    import anvyc.core.cost.adapters.github as gh_mod

    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "httpx":
            raise ImportError("no module 'httpx'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(CostAdapterDepMissingError) as exc_info:
        gh_mod._require_httpx()
    assert exc_info.value.source == "github"
    assert exc_info.value.group == "cost-github"


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_registry_includes_github_when_httpx_available() -> None:
    import importlib.util

    if importlib.util.find_spec("httpx") is None:
        pytest.skip("httpx not installed")
    from anvyc.core.cost.adapters import ADAPTER_REGISTRY

    assert "github" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["github"].name == "github"


def test_build_registry_excludes_github_when_httpx_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util as iutil

    original_find_spec = iutil.find_spec

    def _fake_find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "httpx":
            return None
        return original_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(iutil, "find_spec", _fake_find_spec)
    from anvyc.core.cost.adapters import _build_registry  # noqa: PLC0415

    registry = _build_registry()
    assert "github" not in registry
    assert "anthropic" in registry
