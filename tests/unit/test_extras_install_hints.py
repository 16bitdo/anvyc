"""core/extras ↔ core/install_method 연결 — pyextra 안내가 설치 방식을 따르고 extras 를 보존."""

from __future__ import annotations

import pytest

import anvyc
from anvyc.core import extras as ex
from anvyc.core import install_method as im
from anvyc.core.install_method import INSTALL_SH_URL, InstallContext

_SH = f"bash <(curl -sSL {INSTALL_SH_URL})"


@pytest.fixture
def uv_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(im, "detect", lambda: InstallContext("uv-tool", "/py"))
    monkeypatch.setattr(anvyc, "__version__", "1.2.3")


def test_installed_pip_extras_follow_registry_order(monkeypatch: pytest.MonkeyPatch) -> None:
    present = {"boto3", "mcp"}
    monkeypatch.setattr(ex, "_pyextra_version", lambda req: "1" if req.name in present else None)
    assert ex.installed_pip_extras() == ("mcp", "cost-aws")


def test_order_extras_registry_first_then_unknown_sorted() -> None:
    assert ex._order_extras({"zzz", "cost-aws", "mcp", "aaa"}) == ["mcp", "cost-aws", "aaa", "zzz"]


def test_hint_keeps_installed_extras(monkeypatch: pytest.MonkeyPatch, uv_tool: None) -> None:
    monkeypatch.setattr(ex, "installed_pip_extras", lambda: ("mcp", "tui"))
    assert ex.install_hint_for_extra("cost-aws") == (
        f"ANVYC_VERSION=v1.2.3 ANVYC_EXTRAS=mcp,tui,cost-aws {_SH}"
    )


def test_install_hint_routes_pyextra_by_name(
    monkeypatch: pytest.MonkeyPatch, uv_tool: None
) -> None:
    monkeypatch.setattr(ex, "installed_pip_extras", lambda: ())
    assert ex.install_hint("boto3") == f"ANVYC_VERSION=v1.2.3 ANVYC_EXTRAS=cost-aws {_SH}"
    assert ex.install_hint("boto3") == ex.install_hint_for_extra("cost-aws")


def test_unknown_extra_key_still_gets_a_command(
    monkeypatch: pytest.MonkeyPatch, uv_tool: None
) -> None:
    monkeypatch.setattr(ex, "installed_pip_extras", lambda: ("mcp",))
    assert ex.install_hint_for_extra("future-x") == (
        f"ANVYC_VERSION=v1.2.3 ANVYC_EXTRAS=mcp,future-x {_SH}"
    )


def test_binary_hint_unchanged() -> None:
    assert ex.install_hint("sops").startswith("brew install sops")


def test_collect_status_pyextra_command_is_runtime_hint(
    monkeypatch: pytest.MonkeyPatch, uv_tool: None
) -> None:
    monkeypatch.setattr(ex, "installed_pip_extras", lambda: ())
    for row in ex.collect_extras_status():
        if row["kind"] == "pyextra":
            assert row["install_cmd"] == ex.install_hint_for_extra(row["pip_extra"])
        else:
            req = ex.find(row["name"])
            assert req is not None
            assert row["install_cmd"] == req.install_cmd


def test_hint_for_several_extras_merges_with_installed(
    monkeypatch: pytest.MonkeyPatch, uv_tool: None
) -> None:
    """행별 명령은 표시 시점 상태로 계산돼 서로를 모른다 — 여러 개는 합산 명령 하나로(리뷰 I-1)."""
    monkeypatch.setattr(ex, "installed_pip_extras", lambda: ("tui",))
    assert ex.install_hint_for_extras(["cost-aws", "mcp"]) == (
        f"ANVYC_VERSION=v1.2.3 ANVYC_EXTRAS=mcp,tui,cost-aws {_SH}"
    )
    assert ex.install_hint_for_extra("mcp") == ex.install_hint_for_extras(["mcp"])
