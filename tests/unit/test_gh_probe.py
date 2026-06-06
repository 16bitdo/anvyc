"""core/gh_probe — per-dir 토큰 만료 probe (opt-in, 네트워크).

subprocess.run 을 mock 해 실제 네트워크 없이 테스트한다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from anvyc.core.gh_probe import GhProbeResult, probe_token_expiry


def _fake_run_factory(stdout: str, returncode: int = 0):  # type: ignore[no-untyped-def]
    """stdout / returncode 를 고정한 fake subprocess.run 반환."""

    def fake_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")

    return fake_run


# ---------------------------------------------------------------------------
# Test 1 — 헤더 존재 + 미래 만료 → valid
# ---------------------------------------------------------------------------
def test_header_future_expiry_valid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """X-GitHub-Token-Expiration 헤더가 있고 만료가 미래 → status='valid'."""
    stdout = (
        "HTTP/2 200\r\n"
        "content-type: application/json\r\n"
        "X-GitHub-Token-Expiration: 2099-01-01 00:00:00 UTC\r\n"
        "\r\n"
        '{"login": "16bitdo"}\n'
    )
    monkeypatch.setattr("anvyc.core.gh_probe.subprocess.run", _fake_run_factory(stdout))
    result = probe_token_expiry(tmp_path, "github.com", "16bitdo")
    assert result.status == "valid"
    assert result.expires_at == "2099-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Test 2 — 헤더 존재 + 과거 만료 → expired
# ---------------------------------------------------------------------------
def test_header_past_expiry_expired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """X-GitHub-Token-Expiration 헤더가 있고 만료가 과거 → status='expired'."""
    stdout = (
        "HTTP/2 200\r\n"
        "X-GitHub-Token-Expiration: 2000-01-01 00:00:00 UTC\r\n"
        "\r\n"
        '{"login": "16bitdo"}\n'
    )
    monkeypatch.setattr("anvyc.core.gh_probe.subprocess.run", _fake_run_factory(stdout))
    result = probe_token_expiry(tmp_path, "github.com", "16bitdo")
    assert result.status == "expired"
    assert result.expires_at == "2000-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Test 3 — 헤더 없음 → unknown
# ---------------------------------------------------------------------------
def test_no_expiration_header_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """X-GitHub-Token-Expiration 헤더 없음 → status='unknown', expires_at=None."""
    stdout = 'HTTP/2 200\r\ncontent-type: application/json\r\n\r\n{"login": "16bitdo"}\n'
    monkeypatch.setattr("anvyc.core.gh_probe.subprocess.run", _fake_run_factory(stdout))
    result = probe_token_expiry(tmp_path, "github.com", "16bitdo")
    assert result.status == "unknown"
    assert result.expires_at is None


# ---------------------------------------------------------------------------
# Test 4 — gh 미설치 → FileNotFoundError → graceful unknown
# ---------------------------------------------------------------------------
def test_gh_missing_file_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """gh 가 PATH 에 없어 FileNotFoundError 발생 → GhProbeResult('unknown', None), 예외 없음."""

    def raise_not_found(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("gh not found")

    monkeypatch.setattr("anvyc.core.gh_probe.subprocess.run", raise_not_found)
    result = probe_token_expiry(tmp_path, "github.com", "16bitdo")
    assert result == GhProbeResult(status="unknown", expires_at=None)


# ---------------------------------------------------------------------------
# Test 5 — TimeoutExpired → graceful unknown
# ---------------------------------------------------------------------------
def test_timeout_returns_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """subprocess.TimeoutExpired → GhProbeResult('unknown', None), 예외 없음."""

    def raise_timeout(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="gh", timeout=8.0)

    monkeypatch.setattr("anvyc.core.gh_probe.subprocess.run", raise_timeout)
    result = probe_token_expiry(tmp_path, "github.com", "16bitdo")
    assert result == GhProbeResult(status="unknown", expires_at=None)


# ---------------------------------------------------------------------------
# Test 6 — GH_CONFIG_DIR 가 subprocess.run env 에 올바르게 주입되는지 검증
# ---------------------------------------------------------------------------
def test_gh_config_dir_injected_in_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """subprocess.run 에 env['GH_CONFIG_DIR'] == str(config_dir) 가 전달되는지 확인."""
    captured: dict[str, Any] = {}

    def capturing_run(*_args, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("anvyc.core.gh_probe.subprocess.run", capturing_run)
    config_dir = tmp_path / "gh-16bitdo"
    probe_token_expiry(config_dir, "github.com", "16bitdo")
    assert "env" in captured
    assert captured["env"]["GH_CONFIG_DIR"] == str(config_dir)


# ---------------------------------------------------------------------------
# Test 7 — non-zero returncode (헤더가 있어도) → graceful unknown
# ---------------------------------------------------------------------------
def test_nonzero_returncode_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """gh 가 비0 종료(예: 401)면 stdout 헤더 무관하게 status='unknown'."""
    stdout = "HTTP/2 401\r\nX-GitHub-Token-Expiration: 2099-01-01 00:00:00 UTC\r\n\r\n"
    monkeypatch.setattr(
        "anvyc.core.gh_probe.subprocess.run", _fake_run_factory(stdout, returncode=1)
    )
    result = probe_token_expiry(tmp_path, "github.com", "16bitdo")
    assert result == GhProbeResult(status="unknown", expires_at=None)


# ---------------------------------------------------------------------------
# Test 8 — 파싱 불가 만료 값 → graceful unknown (raw → _classify ValueError)
# ---------------------------------------------------------------------------
def test_unparseable_expiry_header_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """만료 헤더 값이 비표준이라 파싱 실패 → status='unknown' (raise 없음)."""
    stdout = "HTTP/2 200\r\nX-GitHub-Token-Expiration: not-a-date\r\n\r\n"
    monkeypatch.setattr("anvyc.core.gh_probe.subprocess.run", _fake_run_factory(stdout))
    result = probe_token_expiry(tmp_path, "github.com", "16bitdo")
    assert result.status == "unknown"
