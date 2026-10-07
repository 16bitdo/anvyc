"""core/extras ↔ core/install_method 연결 — pyextra 안내가 설치 방식을 따르고 extras 를 보존."""

from __future__ import annotations

import dataclasses
import importlib.metadata as md
import os
from pathlib import Path

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
    monkeypatch.setattr(ex, "_installed_here", lambda req: req.name in present, raising=False)
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


# --- 이 설치본의 extras = 이 환경에 직접 설치된 것 (2026-10-07 v0.24.0 brew 검증 후속) ---


def _site_with(root: Path, name: str, version: str = "1.0") -> Path:
    """root 아래 site-packages 에 최소 dist-info — importlib.metadata 가 실제로 찾는다."""
    site = root / "lib" / "site-packages"
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"  # wheel 규칙: 이름의 - 는 _
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    return site


def _req_probing(name: str) -> ex.ExtraReq:
    req = ex.find("boto3")
    assert req is not None
    return dataclasses.replace(req, probe=(name,))


def test_dist_installed_in_this_venv_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(_site_with(tmp_path / "venv", "anvyc-probe-local")))
    req = _req_probing("anvyc-probe-local")
    assert ex._installed_here(req, prefix=str(tmp_path / "venv"), base_prefix=str(tmp_path / "base"))


def test_global_dist_seen_through_venv_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Homebrew formula venv 는 --system-site-packages — 전역 dist 는 이 설치본의 extras 가 아니다."""
    monkeypatch.syspath_prepend(str(_site_with(tmp_path / "brew", "anvyc-probe-global")))
    assert md.version("anvyc-probe-global") == "1.0"  # 전제: 보이고(import 가능) — 위치만 전역
    req = _req_probing("anvyc-probe-global")
    assert not ex._installed_here(
        req, prefix=str(tmp_path / "venv"), base_prefix=str(tmp_path / "base")
    )


def test_venv_copy_shadows_global_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(_site_with(tmp_path / "brew", "anvyc-probe-both")))
    monkeypatch.syspath_prepend(str(_site_with(tmp_path / "venv", "anvyc-probe-both")))
    req = _req_probing("anvyc-probe-both")
    assert ex._installed_here(req, prefix=str(tmp_path / "venv"), base_prefix=str(tmp_path / "base"))


def test_outside_a_venv_every_visible_dist_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """시스템 python·--user 설치 — 격리가 없으니 보이는 것이 곧 이 설치본이다."""
    monkeypatch.syspath_prepend(str(_site_with(tmp_path / "user-site", "anvyc-probe-user")))
    req = _req_probing("anvyc-probe-user")
    root = str(tmp_path / "sys")
    assert ex._installed_here(req, prefix=root, base_prefix=root)


def test_absent_dist_does_not_count(tmp_path: Path) -> None:
    req = _req_probing("anvyc-probe-absent-zzz")
    assert not ex._installed_here(
        req, prefix=str(tmp_path / "venv"), base_prefix=str(tmp_path / "base")
    )


class _NoLocation(md.Distribution):
    """경로가 없는 dist(zip·사용자 정의 finder) — locate_file 이 동작하지 않는다."""

    def read_text(self, filename: str) -> str | None:
        return None

    def locate_file(self, path: str | os.PathLike[str]) -> Path:
        raise NotImplementedError


def test_unknown_location_counts(tmp_path: Path) -> None:
    """위치를 모르면 센다 — 과소 판정은 재설치가 그 extras 를 지운다."""
    assert ex._in_this_env(
        _NoLocation(), prefix=str(tmp_path / "venv"), base_prefix=str(tmp_path / "base")
    )


def test_homebrew_hint_omits_extras_only_visible_globally(monkeypatch: pytest.MonkeyPatch) -> None:
    """brew venv 에서 전역 httpx·cryptography 가 보여도 안내는 요청한 extra 만(v0.24.0 brew 검증 실측)."""
    monkeypatch.setattr(im, "detect", lambda: InstallContext("homebrew", "/py"))
    monkeypatch.setattr(anvyc, "__version__", "0.24.0")
    visible = {"httpx", "cryptography"}
    monkeypatch.setattr(ex, "_pyextra_version", lambda req: "1" if req.name in visible else None)
    monkeypatch.setattr(ex, "_installed_here", lambda req: False, raising=False)
    assert ex.install_hint_for_extra("mcp").startswith(f"ANVYC_EXTRAS=mcp {_SH}  # Homebrew")


def test_missing_extras_follow_importability_not_install_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """missing 은 check 와 같은 기준(import 가능) — 전역으로 보이는 extra 는 '없음' 이 아니다."""
    monkeypatch.setattr(ex, "_pyextra_version", lambda req: None if req.name == "boto3" else "1")
    monkeypatch.setattr(ex, "_installed_here", lambda req: False, raising=False)
    assert ex.missing_pip_extras() == ("cost-aws",)
