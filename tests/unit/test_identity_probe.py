"""실체 역참조 — subprocess 를 monkeypatch 로 대체해 네트워크 없이 검증."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, NoReturn

import pytest

from anvyc.core import identity_probe


class _Proc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_gh_login_returns_actual_account(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> _Proc:
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        return _Proc(stdout="heisgone\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert identity_probe.gh_login("~/.config/gh-16bitdo") == "heisgone"
    assert captured["cmd"][:3] == ["gh", "api", "user"]
    assert captured["env"]["GH_CONFIG_DIR"].endswith("/.config/gh-16bitdo")
    assert "~" not in captured["env"]["GH_CONFIG_DIR"]
    assert Path(captured["env"]["GH_CONFIG_DIR"]).is_absolute()


def test_gh_login_returns_none_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(returncode=1))
    assert identity_probe.gh_login("~/.config/gh-none") is None


def test_gh_login_returns_none_when_gh_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> NoReturn:
        raise FileNotFoundError("gh")

    monkeypatch.setattr(subprocess, "run", boom)
    assert identity_probe.gh_login("~/.config/gh-16bitdo") is None


def test_ssh_login_parses_greeting_from_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _Proc(returncode=1, stderr="Hi 16bitdo! You've successfully authenticated"),
    )
    assert identity_probe.ssh_login("github.com-16bitdo") == "16bitdo"


def test_ssh_login_returns_none_on_unknown_greeting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(returncode=255, stderr="Permission denied"))
    assert identity_probe.ssh_login("github.com-nope") is None


def test_commit_email_extracts_from_ident(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _Proc(stdout="16bitdo <16bitdo@gmail.com> 1786501165 +0900\n"),
    )
    assert identity_probe.commit_email(Path("/tmp/repo")) == "16bitdo@gmail.com"


def test_commit_email_none_when_identity_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(returncode=128, stderr="Author identity unknown"))
    assert identity_probe.commit_email(Path("/tmp/repo")) is None
