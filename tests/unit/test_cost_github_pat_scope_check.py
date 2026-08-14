"""cost-github-pat-scope doctor check 단위 테스트 (CP-13 PR-13D)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.cost_github_pat_scope import (
    CHECK_NAME,
    CostGithubPatScopeCheck,
)


def _mock_one_account(user: str = "16bitdo", config_dir: str = "/tmp/gh") -> Any:
    """discover_gh_accounts 가 1 user 반환하도록 mock."""
    from pathlib import Path

    acct = MagicMock()
    acct.user = user
    acct.host = "github.com"
    acct.config_dir = Path(config_dir)
    return [acct]


def _make_fake_httpx(status: int, body: str = "") -> MagicMock:
    fake = MagicMock()
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.return_value = resp
    fake.Client.return_value = client
    fake.RequestError = type("FakeRequestError", (Exception,), {})
    return fake


def test_httpx_missing_yields_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._httpx_available",
        lambda: False,
    )
    res = CostGithubPatScopeCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert res[0].check_name == CHECK_NAME
    assert "httpx" in res[0].message
    assert res[0].suggestion is not None
    assert "anvyc[cost-github]" in res[0].suggestion


def test_no_accounts_yields_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._httpx_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope.discover_gh_accounts",
        lambda: [],
    )
    assert CostGithubPatScopeCheck().run(CheckContext()) == []


def test_no_token_yields_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._httpx_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope.discover_gh_accounts",
        _mock_one_account,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._gh_auth_token",
        lambda *a, **k: None,
    )
    res = CostGithubPatScopeCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "16bitdo" in res[0].message
    assert "gh auth status" in (res[0].suggestion or "")


def test_200_yields_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._httpx_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope.discover_gh_accounts",
        _mock_one_account,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._gh_auth_token",
        lambda *a, **k: "ghp_fake",
    )

    fake_httpx = _make_fake_httpx(200, "{}")
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        res = CostGithubPatScopeCheck().run(CheckContext())
    assert res == []


def test_401_yields_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._httpx_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope.discover_gh_accounts",
        _mock_one_account,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._gh_auth_token",
        lambda *a, **k: "ghp_fake",
    )

    fake_httpx = _make_fake_httpx(401, "Bad credentials")
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        res = CostGithubPatScopeCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "401" in res[0].message
    assert res[0].suggestion is not None
    # 최소 해법(기존 토큰에 scope 추가)을 먼저 안내하고 PAT 은 대안으로 병기 (#192 ④)
    assert "gh auth refresh" in res[0].suggestion
    assert "-s user" in res[0].suggestion
    assert "Plan: Read-only" in res[0].suggestion


def test_404_enhanced_disabled_yields_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._httpx_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope.discover_gh_accounts",
        _mock_one_account,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._gh_auth_token",
        lambda *a, **k: "ghp_fake",
    )

    fake_httpx = _make_fake_httpx(
        404, "Enhanced billing platform not enabled"
    )
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        res = CostGithubPatScopeCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "Enhanced Billing Platform" in res[0].message


def test_network_error_yields_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._httpx_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope.discover_gh_accounts",
        _mock_one_account,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._gh_auth_token",
        lambda *a, **k: "ghp_fake",
    )

    fake_httpx = MagicMock()
    fake_httpx.RequestError = type("FakeRequestError", (Exception,), {})
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.side_effect = fake_httpx.RequestError("connection reset")
    fake_httpx.Client.return_value = client

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        res = CostGithubPatScopeCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "네트워크" in res[0].message


def test_check_registered_in_doctor() -> None:
    """doctor _REGISTRY 에 cost-github-pat-scope 키 존재 검증."""
    from anvyc.core.doctor import _REGISTRY  # noqa: PLC0415

    assert "cost-github-pat-scope" in _REGISTRY
    assert _REGISTRY["cost-github-pat-scope"].name == "cost-github-pat-scope"
