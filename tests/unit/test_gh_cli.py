"""anvyc gh CLI 와이어링 테스트."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def test_gh_passes_args_and_returns_code(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr("anvyc.core.gh_route.resolve_account", lambda start: "16bitdo")

    def fake_run_gh(account: str, args: list[str]) -> int:
        seen["account"] = account
        seen["args"] = args
        return 0

    monkeypatch.setattr("anvyc.core.gh_route.run_gh", fake_run_gh)

    result = runner.invoke(app, ["gh", "pr", "create", "--title", "x"])
    assert result.exit_code == 0
    assert seen["account"] == "16bitdo"
    assert seen["args"] == ["pr", "create", "--title", "x"]


def test_gh_exits_2_when_account_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("anvyc.core.gh_route.resolve_account", lambda start: None)
    result = runner.invoke(app, ["gh", "pr", "list"])
    assert result.exit_code == 2
    assert "account" in result.output.lower()


def test_gh_propagates_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("anvyc.core.gh_route.resolve_account", lambda start: "16bitdo")
    monkeypatch.setattr("anvyc.core.gh_route.run_gh", lambda account, args: 7)
    result = runner.invoke(app, ["gh", "api", "x"])
    assert result.exit_code == 7
