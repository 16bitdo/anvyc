"""venv-hidden-flag check 단위 테스트."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.venv_hidden import VenvHiddenFlagCheck

_SITE_PACKAGES = "lib/python3.13/site-packages"


def _make_fake_venv(tmp_path: Path, pth_names: list[str]) -> Path:
    """`<tmp>/.venv/lib/python3.13/site-packages/` 에 .pth 파일들을 만든다."""
    venv = tmp_path / ".venv"
    sp = venv / _SITE_PACKAGES
    sp.mkdir(parents=True)
    for name in pth_names:
        (sp / name).write_text("dummy\n")
    return venv


def _point_sys_at(monkeypatch: pytest.MonkeyPatch, venv_root: Path) -> None:
    """_venv_root() 가 venv_root 를 인식하도록 sys.prefix 를 가리킨다."""
    monkeypatch.setattr(sys, "prefix", str(venv_root))
    monkeypatch.setattr(sys, "base_prefix", str(venv_root) + "_base")
    monkeypatch.delattr(sys, "real_prefix", raising=False)


def _install_fake_is_hidden(
    monkeypatch: pytest.MonkeyPatch, hidden: set[Path]
) -> None:
    """_is_hidden 을 stub — hidden set 의 경로만 True (platform-independent)."""
    resolved = {p.resolve(strict=False) for p in hidden}

    def _fake(path: Path) -> bool:
        return path.resolve(strict=False) in resolved

    monkeypatch.setattr(VenvHiddenFlagCheck, "_is_hidden", staticmethod(_fake))


def test_non_darwin_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert VenvHiddenFlagCheck().run(CheckContext()) == []


def test_no_venv_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "prefix", "/usr/local")
    monkeypatch.setattr(sys, "base_prefix", "/usr/local")
    monkeypatch.delattr(sys, "real_prefix", raising=False)
    assert VenvHiddenFlagCheck().run(CheckContext()) == []


def test_no_hidden_pth_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    venv = _make_fake_venv(tmp_path, ["_editable_impl_anvyc.pth"])
    _point_sys_at(monkeypatch, venv)
    _install_fake_is_hidden(monkeypatch, set())
    assert VenvHiddenFlagCheck().run(CheckContext()) == []


def test_editable_shim_hidden_yields_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    venv = _make_fake_venv(tmp_path, ["_editable_impl_anvyc.pth"])
    _point_sys_at(monkeypatch, venv)
    pth = venv / _SITE_PACKAGES / "_editable_impl_anvyc.pth"
    _install_fake_is_hidden(monkeypatch, {pth})

    res = VenvHiddenFlagCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].check_name == "venv-hidden-flag"
    assert res[0].severity is Severity.WARNING
    assert "editable install" in res[0].message
    assert res[0].location == pth


def test_plain_pth_hidden_does_not_claim_editable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    venv = _make_fake_venv(tmp_path, ["_virtualenv.pth"])
    _point_sys_at(monkeypatch, venv)
    pth = venv / _SITE_PACKAGES / "_virtualenv.pth"
    _install_fake_is_hidden(monkeypatch, {pth})

    res = VenvHiddenFlagCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "editable install" not in res[0].message


def test_mixed_prioritizes_editable_shim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    venv = _make_fake_venv(tmp_path, ["_editable_impl_anvyc.pth", "_virtualenv.pth"])
    _point_sys_at(monkeypatch, venv)
    sp = venv / _SITE_PACKAGES
    shim = sp / "_editable_impl_anvyc.pth"
    plain = sp / "_virtualenv.pth"
    _install_fake_is_hidden(monkeypatch, {shim, plain})

    res = VenvHiddenFlagCheck().run(CheckContext())
    assert len(res) == 1
    assert "editable install" in res[0].message
    assert res[0].location == shim


def test_suggestion_mentions_chflags_wrapper_and_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    venv = _make_fake_venv(tmp_path, ["_editable_impl_anvyc.pth"])
    _point_sys_at(monkeypatch, venv)
    pth = venv / _SITE_PACKAGES / "_editable_impl_anvyc.pth"
    _install_fake_is_hidden(monkeypatch, {pth})

    suggestion = VenvHiddenFlagCheck().run(CheckContext())[0].suggestion or ""
    assert "chflags" in suggestion
    assert "wrapper" in suggestion
    assert "troubleshooting-macos.md" in suggestion
    assert "임시" in suggestion


def test_is_editable_shim_helper() -> None:
    f = VenvHiddenFlagCheck._is_editable_shim
    assert f(Path("_editable_impl_anvyc.pth")) is True
    assert f(Path("__editable__.anvyc-0.10.0.pth")) is True
    assert f(Path("_virtualenv.pth")) is False
    assert f(Path("a1_coverage.pth")) is False
    assert f(Path("site-packages")) is False
    assert f(Path("_editable_impl_anvyc.py")) is False


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS chflags")
def test_real_chflags_hidden_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venv = _make_fake_venv(tmp_path, ["_editable_impl_anvyc.pth"])
    _point_sys_at(monkeypatch, venv)
    pth = venv / _SITE_PACKAGES / "_editable_impl_anvyc.pth"
    os.chflags(pth, stat.UF_HIDDEN)
    try:
        assert VenvHiddenFlagCheck._is_hidden(pth) is True
        res = VenvHiddenFlagCheck().run(CheckContext())
        assert len(res) == 1
        assert res[0].severity is Severity.WARNING
        assert "editable install" in res[0].message
    finally:
        os.chflags(pth, 0)


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS chflags")
def test_real_chflags_clean_no_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venv = _make_fake_venv(tmp_path, ["_editable_impl_anvyc.pth"])
    _point_sys_at(monkeypatch, venv)
    pth = venv / _SITE_PACKAGES / "_editable_impl_anvyc.pth"
    os.chflags(pth, 0)
    assert VenvHiddenFlagCheck._is_hidden(pth) is False
    assert VenvHiddenFlagCheck().run(CheckContext()) == []
