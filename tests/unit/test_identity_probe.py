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


# ---------------------------------------------------------------------------
# GH_TOKEN 주입 — GH_CONFIG_DIR 만으로는 "이 프로필의 계정" 을 알 수 없다.
#
# 2026-08-14 실측: 주변 GH_TOKEN 을 바꾸면 이 함수의 답이 통째로 뒤집혔다. 계정이
# N 개면 활성인 하나만 맞고 나머지 N-1 개가 전부 불일치로 보고됐다. 아래 테스트는
# "주변 환경이 답을 바꾸지 못한다" 를 고정한다.
# ---------------------------------------------------------------------------


def _two_call_runner(
    captured: list[dict[str, Any]], token: str = "tok", login: str = "heisgone"
) -> Any:
    """`gh auth token` -> token, `gh api user` -> login 으로 답하는 fake."""

    def fake_run(cmd: list[str], **kwargs: object) -> _Proc:
        captured.append({"cmd": cmd, "env": kwargs.get("env") or {}})
        if cmd[:3] == ["gh", "auth", "token"]:
            return _Proc(stdout=f"{token}\n")
        return _Proc(stdout=f"{login}\n")

    return fake_run


def test_gh_login_resolves_the_profile_account_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """디렉터리에서 계정을 역산해 그 계정의 토큰을 꺼내 쓴다."""
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", _two_call_runner(captured))

    assert identity_probe.gh_login("~/.config/gh-heisgone") == "heisgone"

    assert captured[0]["cmd"] == ["gh", "auth", "token", "--user", "heisgone"]
    assert captured[1]["cmd"][:3] == ["gh", "api", "user"]
    assert captured[1]["env"]["GH_TOKEN"] == "tok"


def test_gh_login_overrides_ambient_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """주변 GH_TOKEN 을 상속하면 호출 환경에 따라 답이 달라진다 — 반드시 덮어쓴다."""
    monkeypatch.setenv("GH_TOKEN", "someone-elses-token")
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", _two_call_runner(captured, token="profile-tok"))

    identity_probe.gh_login("~/.config/gh-heisgone")

    assert captured[1]["env"]["GH_TOKEN"] == "profile-tok"


def test_gh_login_is_none_when_token_lookup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """토큰을 못 얻으면 '모름'. 주변 토큰으로 폴백하면 다른 계정의 신원을
    이 프로필의 실체라고 보고하게 된다 — 침묵보다 나쁘다."""
    monkeypatch.setenv("GH_TOKEN", "someone-elses-token")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> _Proc:
        calls.append(cmd)
        return _Proc(returncode=1)  # gh auth token 실패

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert identity_probe.gh_login("~/.config/gh-heisgone") is None
    # 토큰 없이 gh api user 를 부르지 않았는가 — 부르면 주변 토큰으로 조회된다.
    assert all(c[:3] != ["gh", "api", "user"] for c in calls)


def test_gh_login_is_none_for_non_convention_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.../gh-<account>` 관례를 벗어나면 어느 계정의 토큰을 쓸지 알 수 없다."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> _Proc:
        calls.append(cmd)
        return _Proc(stdout="16bitdo\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert identity_probe.gh_login("~/.config/some-other-dir") is None
    assert calls == []  # subprocess 자체를 부르지 않는다


def test_gh_login_ambient_token_cannot_flip_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """같은 프로필을 서로 다른 주변 환경에서 조회해도 답이 같아야 한다.

    수정 전에는 주변 GH_TOKEN 이 답을 결정해 두 호출의 결과가 갈렸다.
    """
    results = []
    for ambient in ("token-a", "token-b"):
        monkeypatch.setenv("GH_TOKEN", ambient)
        monkeypatch.setattr(
            subprocess, "run", _two_call_runner([], token="profile-tok", login="heisgone")
        )
        results.append(identity_probe.gh_login("~/.config/gh-heisgone"))
    assert results == ["heisgone", "heisgone"]
