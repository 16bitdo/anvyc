"""anvyc github account list/show CLI (Phase 1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def _home(tmp_path: Path) -> Path:
    """두 개의 gh config dir 을 가진 tmp HOME 구성.

    - ~/.config/gh-16bitdo  → github.com / 16bitdo
    - ~/.config/gh-heisgone → github.com / heisgone
    토큰 값 ghp_X 를 포함 — 출력 노출 회귀 가드에 사용.
    """
    cfg = tmp_path / ".config"
    for dirname, host, user in [
        ("gh-16bitdo", "github.com", "16bitdo"),
        ("gh-heisgone", "github.com", "heisgone"),
    ]:
        d = cfg / dirname
        d.mkdir(parents=True, exist_ok=True)
        (d / "hosts.yml").write_text(
            f"{host}:\n    users:\n        {user}:\n            oauth_token: ghp_X\n",
            encoding="utf-8",
        )
    return tmp_path


# ---------------------------------------------------------------------------
# github account list
# ---------------------------------------------------------------------------


def test_list_human(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """계정 이름 두 개 모두 human 출력에 나타난다."""
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["github", "account", "list"])
    assert result.exit_code == 0, result.output
    assert "16bitdo" in result.output
    assert "heisgone" in result.output


def test_list_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json 출력이 파싱 가능하고 필수 키를 포함하며 probe 없이 expiry_status=="unknown"."""
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["github", "account", "list", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    accounts = {a["account"]: a for a in data["accounts"]}
    assert "16bitdo" in accounts
    assert "heisgone" in accounts
    # probe 없이는 expiry_status == "unknown"
    assert accounts["16bitdo"]["expiry_status"] == "unknown"
    # 필수 키 존재 확인
    required_keys = {
        "account",
        "host",
        "config_dir",
        "logged_in",
        "expiry_status",
        "expires_at",
        "routed_owners",
        "cwd_routed",
    }
    assert required_keys <= set(accounts["16bitdo"].keys())


def test_list_no_token_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ghp_X 토큰 값이 어떤 출력에도 나타나지 않는다."""
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    for args in [["github", "account", "list"], ["github", "account", "list", "--json"]]:
        result = runner.invoke(app, args)
        assert "ghp_X" not in result.output, f"token leaked in {args}: {result.output!r}"


def test_list_empty_no_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """gh config dir 없을 때 exit 0 + 힌트 출력."""
    # 빈 .config 디렉터리 (gh* 없음)
    (tmp_path / ".config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["github", "account", "list"])
    assert result.exit_code == 0, result.output
    # 힌트 문자열 존재
    assert "gh auth login" in result.output


def test_list_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--probe 시 probe_token_expiry 가 호출되고 status 가 출력된다."""
    monkeypatch.setenv("HOME", str(_home(tmp_path)))

    from anvyc.core import gh_probe as _gh_probe_mod

    def fake_probe(
        config_dir: Path, host: str, user: str, **_k: object
    ) -> _gh_probe_mod.GhProbeResult:
        return _gh_probe_mod.GhProbeResult(status="valid", expires_at="2099-01-01T00:00:00Z")

    monkeypatch.setattr(_gh_probe_mod, "probe_token_expiry", fake_probe)

    result = runner.invoke(app, ["github", "account", "list", "--probe", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    accounts = {a["account"]: a for a in data["accounts"]}
    assert accounts["16bitdo"]["expiry_status"] == "valid"
    assert accounts["16bitdo"]["expires_at"] == "2099-01-01T00:00:00Z"


def test_list_no_probe_not_called(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--probe 없을 때 probe_token_expiry 가 호출되지 않는다.

    patch 해서 호출 시 예외를 내도록 — list 는 exit 0 이어야 한다.
    """
    monkeypatch.setenv("HOME", str(_home(tmp_path)))

    from anvyc.core import gh_probe as _gh_probe_mod

    def _should_not_be_called(*_a: object, **_kw: object) -> None:
        raise AssertionError("probe_token_expiry should NOT be called without --probe")

    monkeypatch.setattr(_gh_probe_mod, "probe_token_expiry", _should_not_be_called)

    result = runner.invoke(app, ["github", "account", "list"])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# github account show
# ---------------------------------------------------------------------------


def test_show_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """known account 를 show 하면 exit 0."""
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["github", "account", "show", "16bitdo"])
    assert result.exit_code == 0, result.output
    assert "16bitdo" in result.output


def test_show_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json 단일 객체 반환."""
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["github", "account", "show", "16bitdo", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["account"] == "16bitdo"
    assert data["expiry_status"] == "unknown"


def test_show_not_found_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """없는 account 는 exit 1."""
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["github", "account", "show", "ghost"])
    assert result.exit_code == 1


def test_show_no_token_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """show 출력에 토큰 값이 노출되지 않는다."""
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["github", "account", "show", "16bitdo", "--json"])
    assert "ghp_X" not in result.output


def test_show_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """show --probe 시 해당 계정에 대해 probe 가 호출된다."""
    monkeypatch.setenv("HOME", str(_home(tmp_path)))

    from anvyc.core import gh_probe as _gh_probe_mod

    probed: list[str] = []

    def fake_probe(
        config_dir: Path, host: str, user: str, **_k: object
    ) -> _gh_probe_mod.GhProbeResult:
        probed.append(user)
        return _gh_probe_mod.GhProbeResult(status="expiring", expires_at="2026-07-01T00:00:00Z")

    monkeypatch.setattr(_gh_probe_mod, "probe_token_expiry", fake_probe)

    result = runner.invoke(app, ["github", "account", "show", "16bitdo", "--probe", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["expiry_status"] == "expiring"
    # 대상 계정만 probe (필터 회귀 가드 — heisgone 은 probe 안 함)
    assert probed == ["16bitdo"], f"expected only target probed, got: {probed}"


def test_show_no_probe_not_called(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--probe 없으면 show 도 probe_token_expiry 를 호출하지 않는다 (list 와 대칭)."""
    monkeypatch.setenv("HOME", str(_home(tmp_path)))

    from anvyc.core import gh_probe as _gh_probe_mod

    def _should_not_be_called(*_a: object, **_kw: object) -> None:
        raise AssertionError("probe_token_expiry should NOT be called without --probe")

    monkeypatch.setattr(_gh_probe_mod, "probe_token_expiry", _should_not_be_called)

    result = runner.invoke(app, ["github", "account", "show", "16bitdo"])
    assert result.exit_code == 0, result.output
