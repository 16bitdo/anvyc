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


def _make_fake_httpx(
    status: int, body: str = "", headers: dict[str, str] | None = None
) -> MagicMock:
    fake = MagicMock()
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    resp.headers = headers or {}
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


def test_gh_auth_token_passes_user_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--user` 없이 호출하면 active account 토큰이 반환돼 user 별 검증이
    성립하지 않는다 (#192 ①)."""
    from anvyc.checks.cost_github_pat_scope import _gh_auth_token  # noqa: PLC0415

    captured: dict[str, Any] = {}

    def _fake_run(cmd: list[str], **kwargs: Any) -> Any:
        captured["cmd"] = cmd
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "gho_fake\n"
        return proc

    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope.subprocess.run", _fake_run
    )
    assert _gh_auth_token("/tmp/gh", user="heisgone") == "gho_fake"
    cmd = captured["cmd"]
    assert "--user" in cmd
    assert cmd[cmd.index("--user") + 1] == "heisgone"


def test_config_dir_follows_select_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """사전식 첫 dir 이 아니라 `gh-<user>` 우선 정책을 따라야 한다 (#192 ②)."""
    from pathlib import Path  # noqa: PLC0415

    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._httpx_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope.discover_gh_accounts",
        lambda: _mock_one_account("heisgone", "/tmp/gh"),
    )
    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope.select_config_dir_for_user",
        lambda user: Path(f"/tmp/gh-{user}"),
    )
    seen: dict[str, Any] = {}

    def _fake_token(
        config_dir: str, host: str = "", user: str | None = None
    ) -> str:
        seen["config_dir"] = config_dir
        seen["user"] = user
        return "gho_fake"

    monkeypatch.setattr(
        "anvyc.checks.cost_github_pat_scope._gh_auth_token", _fake_token
    )

    fake_httpx = _make_fake_httpx(200, "{}")
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        CostGithubPatScopeCheck().run(CheckContext())
    assert seen["config_dir"] == "/tmp/gh-heisgone"
    assert seen["user"] == "heisgone"


def test_404_missing_scope_not_reported_as_enhanced_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """scope 부족 404 를 Enhanced Billing 미활성으로 오진하지 않는다 (#192 ③).

    이 endpoint 의 404 body 는 `documentation_url` 에 항상 `/rest/billing/` 을
    포함하므로 문자열 매칭으로는 구분할 수 없다. 근거는 응답 헤더다.
    """
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
        lambda *a, **k: "gho_fake",
    )

    body = (
        '{"message":"Not Found","documentation_url":'
        '"https://docs.github.com/rest/billing/usage'
        '#get-billing-usage-report-for-a-user","status":"404"}'
    )
    fake_httpx = _make_fake_httpx(
        404,
        body,
        headers={
            "X-Accepted-OAuth-Scopes": "user",
            "X-OAuth-Scopes": "gist, read:org, repo, workflow",
        },
    )
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        res = CostGithubPatScopeCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "Enhanced Billing Platform" not in res[0].message
    assert "user" in res[0].message
    assert "gh auth refresh" in (res[0].suggestion or "")


def test_check_registered_in_doctor() -> None:
    """doctor _REGISTRY 에 cost-github-pat-scope 키 존재 검증."""
    from anvyc.core.doctor import _REGISTRY  # noqa: PLC0415

    assert "cost-github-pat-scope" in _REGISTRY
    assert _REGISTRY["cost-github-pat-scope"].name == "cost-github-pat-scope"
