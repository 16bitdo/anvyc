"""core/install_method — 설치 방식 판별과 extras 설치 명령.

spec: docs/superpowers/specs/2026-10-07-install-method-aware-extras-hints-design.md
판별 신호는 2026-10-07 실측(uv receipt 의 url/path/directory, pipx_metadata.json,
Homebrew 의 Cellar/anvyc prefix)을 따른다.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from anvyc.core import install_method as im
from anvyc.core.install_method import (
    InstallContext,
    InstallMethod,
    detect,
    extras_install_command,
)


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


_SH = "bash <(curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)"
_README = "https://github.com/16bitdo/anvyc#57-업그레이드와-extras-추가-설치-방식별"
_WHEEL = (
    "https://github.com/16bitdo/anvyc/releases/download/v0.23.0/anvyc-0.23.0-py3-none-any.whl"
)


@pytest.mark.parametrize(
    ("ctx", "expected"),
    [
        (
            InstallContext("dev", "/py", Path("/r/anvyc")),
            "ANVYC_EXTRAS=dev,mcp,tui,cost-aws bash /r/anvyc/scripts/dev-install.sh",
        ),
        (
            InstallContext("uv-tool", "/py"),
            f"ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp,cost-aws {_SH}",
        ),
        (
            InstallContext("uv-tool-source", "/py", Path("/s/anvyc")),
            "uv tool install --force --reinstall --refresh '/s/anvyc[mcp,cost-aws]'",
        ),
        (
            InstallContext("pipx", "/py"),
            f"ANVYC_METHOD=pipx ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp,cost-aws {_SH}",
        ),
        (
            InstallContext("homebrew", "/py"),
            "Homebrew 설치본은 extras 를 지원하지 않습니다 — install.sh 로 옮기세요: "
            f"ANVYC_EXTRAS=mcp,cost-aws {_SH} (설치 방식별: {_README})",
        ),
        (
            InstallContext("venv", "/v/bin/python"),
            f"/v/bin/python -m pip install 'anvyc[mcp,cost-aws] @ {_WHEEL}'",
        ),
        (
            InstallContext("unknown", "/py"),
            f"ANVYC_EXTRAS=mcp,cost-aws {_SH} (설치 방식별: {_README})",
        ),
    ],
    ids=["dev", "uv-tool", "uv-tool-source", "pipx", "homebrew", "venv", "unknown"],
)
def test_command_per_method(ctx: InstallContext, expected: str) -> None:
    assert extras_install_command(["mcp", "cost-aws"], ctx=ctx, version="0.23.0") == expected


@pytest.mark.parametrize("version", ["0.0.0+unknown", "0.24.0.dev1"])
def test_non_release_version_is_not_pinned(version: str) -> None:
    uv = extras_install_command(["mcp"], ctx=InstallContext("uv-tool", "/py"), version=version)
    assert uv == f"ANVYC_EXTRAS=mcp {_SH}"
    venv = extras_install_command(["mcp"], ctx=InstallContext("venv", "/py"), version=version)
    assert venv == f"ANVYC_EXTRAS=mcp {_SH} (설치 방식별: {_README})"


def test_paths_with_spaces_are_quoted() -> None:
    dev = extras_install_command(
        ["mcp"], ctx=InstallContext("dev", "/py", Path("/My Repos/anvyc")), version="0.23.0"
    )
    assert dev == "ANVYC_EXTRAS=dev,mcp,tui bash '/My Repos/anvyc/scripts/dev-install.sh'"
    venv = extras_install_command(
        ["mcp"], ctx=InstallContext("venv", "/My Envs/v/bin/python"), version="0.23.0"
    )
    assert venv == f"'/My Envs/v/bin/python' -m pip install 'anvyc[mcp] @ {_WHEEL}'"
    src = extras_install_command(
        ["mcp"], ctx=InstallContext("uv-tool-source", "/py", Path("/My Src/anvyc")), version="0.23.0"
    )
    assert src == "uv tool install --force --reinstall --refresh '/My Src/anvyc[mcp]'"


def test_duplicates_removed_order_kept() -> None:
    cmd = extras_install_command(
        ["mcp", "tui", "mcp"], ctx=InstallContext("uv-tool", "/py"), version="0.23.0"
    )
    assert cmd == f"ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp,tui {_SH}"


def test_default_context_and_version_come_from_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(im, "detect", lambda: InstallContext("uv-tool", "/py"))
    monkeypatch.setattr("anvyc.__version__", "9.8.7")
    assert extras_install_command(["mcp"]) == f"ANVYC_VERSION=v9.8.7 ANVYC_EXTRAS=mcp {_SH}"


def test_dev_install_default_extras_match_script() -> None:
    script = (Path(__file__).resolve().parents[2] / "scripts" / "dev-install.sh").read_text(
        encoding="utf-8"
    )
    m = re.search(r'EXTRAS="\$\{ANVYC_EXTRAS:-([a-z0-9,-]+)\}"', script)
    assert m, "dev-install.sh 의 EXTRAS 기본값 줄을 찾지 못했다"
    assert tuple(m[1].split(",")) == im.DEV_INSTALL_DEFAULT_EXTRAS


_METHODS: tuple[InstallMethod, ...] = (
    "dev",
    "uv-tool",
    "uv-tool-source",
    "pipx",
    "homebrew",
    "venv",
    "unknown",
)


@pytest.mark.parametrize("method", _METHODS)
def test_no_generated_command_resolves_the_name_on_pypi(method: InstallMethod) -> None:
    ctx = InstallContext(method, "/py", Path("/s/anvyc"))
    cmd = extras_install_command(["mcp"], ctx=ctx, version="0.23.0")
    assert not re.search(r"(?<![\w/.-])anvyc\[[^\]]*\](?!\s*@)", cmd), cmd
