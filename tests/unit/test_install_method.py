"""core/install_method — 설치 방식 판별과 extras 설치 명령.

spec: docs/superpowers/specs/2026-10-07-install-method-aware-extras-hints-design.md
판별 신호는 2026-10-07 실측(uv receipt 의 url/path/directory, pipx_metadata.json,
Homebrew 의 Cellar/anvyc prefix)을 따른다.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from anvyc.core.install_method import InstallContext, detect


def _receipt(prefix: Path, body: str) -> None:
    prefix.mkdir(parents=True, exist_ok=True)
    (prefix / "uv-receipt.toml").write_text(body, encoding="utf-8")


def _detect(prefix: Path, *, base: Path | None = None) -> InstallContext:
    return detect(
        prefix=prefix,
        base_prefix=base if base is not None else Path("/base"),
        source_repo=None,
        executable="/py",
    )


def test_dev_when_source_repo(tmp_path: Path) -> None:
    ctx = detect(
        prefix=tmp_path, base_prefix=tmp_path, source_repo=Path("/r/anvyc"), executable="/py"
    )
    assert ctx == InstallContext("dev", "/py", Path("/r/anvyc"))


def test_running_from_this_checkout_is_dev() -> None:
    assert detect().method == "dev"


def test_uv_tool_source_from_receipt_directory(tmp_path: Path) -> None:
    _receipt(
        tmp_path,
        '[tool]\nrequirements = [{ name = "anvyc", extras = ["mcp"], directory = "/s/anvyc" }]\n',
    )
    assert _detect(tmp_path) == InstallContext("uv-tool-source", "/py", Path("/s/anvyc"))


@pytest.mark.parametrize("key", ["url", "path"])
def test_uv_tool_from_receipt_url_or_path(tmp_path: Path, key: str) -> None:
    _receipt(
        tmp_path,
        f'[tool]\nrequirements = [{{ name = "anvyc", {key} = "/x/anvyc-0.23.0-py3-none-any.whl" }}]\n',
    )
    assert _detect(tmp_path) == InstallContext("uv-tool", "/py")


@pytest.mark.parametrize(
    "body",
    [
        "not = [valid",
        '[tool]\nrequirements = "oops"\n',
        '[tool]\nrequirements = [{ name = "other" }]\n',
    ],
    ids=["invalid-toml", "not-a-list", "no-anvyc"],
)
def test_broken_or_foreign_receipt_falls_through(tmp_path: Path, body: str) -> None:
    _receipt(tmp_path, body)
    assert _detect(tmp_path).method == "venv"  # 다음 신호(prefix ≠ base)로 — 예외 없음


def test_detect_never_raises_on_unreadable_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _receipt(tmp_path, "[tool]\nrequirements = []\n")

    def boom(*_args: object, **_kwargs: object) -> object:
        raise PermissionError("denied")

    monkeypatch.setattr(tomllib, "load", boom)  # install_method 가 쓰는 같은 모듈 객체
    assert _detect(tmp_path).method == "venv"


def test_pipx_metadata(tmp_path: Path) -> None:
    tmp_path.joinpath("pipx_metadata.json").write_text("{}", encoding="utf-8")
    assert _detect(tmp_path).method == "pipx"


def test_homebrew_cellar_prefix(tmp_path: Path) -> None:
    prefix = tmp_path / "Cellar" / "anvyc" / "0.23.0" / "libexec"
    prefix.mkdir(parents=True)
    assert _detect(prefix).method == "homebrew"


def test_homebrew_via_opt_symlink(tmp_path: Path) -> None:
    real = tmp_path / "Cellar" / "anvyc" / "0.23.0"
    (real / "libexec").mkdir(parents=True)
    opt = tmp_path / "opt"
    opt.mkdir()
    (opt / "anvyc").symlink_to(real)
    assert _detect(opt / "anvyc" / "libexec").method == "homebrew"


def test_other_cellar_formula_is_not_homebrew_anvyc(tmp_path: Path) -> None:
    prefix = tmp_path / "Cellar" / "python@3.13" / "3.13.16"
    prefix.mkdir(parents=True)
    assert _detect(prefix).method == "venv"


def test_venv_when_prefix_differs(tmp_path: Path) -> None:
    assert _detect(tmp_path).method == "venv"


def test_unknown_when_prefix_is_base(tmp_path: Path) -> None:
    assert _detect(tmp_path, base=tmp_path).method == "unknown"
