"""core/aws_probe — aws sts get-caller-identity wrapper (opt-in)."""
import subprocess

import pytest

from anvyc.core import aws_probe
from anvyc.core.aws_probe import ProbeResult, probe_caller_identity


def test_probe_aws_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aws_probe.shutil, "which", lambda _: None)  # type: ignore[attr-defined]
    r = probe_caller_identity("dev")
    assert r.ok is False and "aws CLI" in (r.error or "")


def test_probe_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aws_probe.shutil, "which", lambda _: "/usr/bin/aws")  # type: ignore[attr-defined]

    def fake_run(*_a, **_k):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"Account": "123456789012", "Arn": "arn:aws:iam::1:user/x"}', stderr="",
        )

    monkeypatch.setattr(aws_probe.subprocess, "run", fake_run)  # type: ignore[attr-defined]
    r = probe_caller_identity("dev")
    assert r.ok is True and r.account == "123456789012"


def test_probe_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aws_probe.shutil, "which", lambda _: "/usr/bin/aws")  # type: ignore[attr-defined]

    def fake_run(*_a, **_k):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=[], returncode=255, stdout="", stderr="Unable to locate credentials\n",
        )

    monkeypatch.setattr(aws_probe.subprocess, "run", fake_run)  # type: ignore[attr-defined]
    r = probe_caller_identity("dev")
    assert r.ok is False and "credentials" in (r.error or "")


def test_probe_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aws_probe.shutil, "which", lambda _: "/usr/bin/aws")  # type: ignore[attr-defined]

    def fake_run(*_a, **_k):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="aws", timeout=8.0)

    monkeypatch.setattr(aws_probe.subprocess, "run", fake_run)  # type: ignore[attr-defined]
    assert probe_caller_identity("dev").error == "timeout"


def test_proberesult_dataclass() -> None:
    assert ProbeResult(ok=True, account="1").account == "1"
