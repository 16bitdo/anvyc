"""doctor — extras 설치 안내가 2건 이상 보이면 합산 명령을 한 줄 더 낸다(리뷰 I-1, 2026-10-07).

행별 안내는 표시 시점 상태로 계산돼 서로를 모른다. uv tool·pipx·install.sh 설치본은 재설치가
요구 문자열의 extras 로 환경을 맞추므로, 두 안내를 차례로 실행하면 뒤 명령이 앞 extra 를 지운다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

import anvyc
import anvyc.cli as cli
from anvyc.checks.base import CheckResult, Severity
from anvyc.cli import app
from anvyc.core import extras as ex
from anvyc.core import install_method as im
from anvyc.core.doctor import CheckRun, DoctorReport
from anvyc.core.extras import install_hint, install_hint_for_extras
from anvyc.core.install_method import InstallContext

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture(autouse=True)
def uv_tool_without_extras(monkeypatch: pytest.MonkeyPatch) -> None:
    """재설치형 설치(uv tool), extras 없음 — check 가 안내를 낸 extra 는 실제로도 미설치다.

    '없음'(missing_pip_extras)은 check 와 같은 import 가능 여부로, 안내의 합집합은
    installed_pip_extras 로 판정한다 — 둘 다 비운다.
    """
    monkeypatch.setattr(im, "detect", lambda: InstallContext("uv-tool", "/py"))
    monkeypatch.setattr(anvyc, "__version__", "0.23.0")
    monkeypatch.setattr(ex, "installed_pip_extras", lambda: ())
    monkeypatch.setattr(ex, "_pyextra_version", lambda req: None)


def _report(*findings: tuple[str, str]) -> DoctorReport:
    results = [
        CheckResult(check_name=name, severity=Severity.WARNING, message="missing", suggestion=s)
        for name, s in findings
    ]
    return DoctorReport(results=results, runs=[CheckRun(r.check_name, [r]) for r in results])


@pytest.mark.parametrize("args", [["doctor"], ["doctor", "--verbose"]], ids=["summary", "verbose"])
def test_doctor_prints_one_combined_command_for_two_extras_hints(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    report = _report(
        ("mcp-extra-importable", install_hint("mcp")),
        ("cost-aws-explorer-iam", f"{install_hint('boto3')}  (설치 후 `anvyc cost collect` 가능)"),
    )
    monkeypatch.setattr(cli, "run_doctor", lambda **_kw: report)
    out = _ANSI.sub("", CliRunner().invoke(app, args).output)
    combined = install_hint_for_extras(["mcp", "cost-aws"])
    assert combined in [line.strip() for line in out.splitlines()], out
    assert "서로를 지운다" in out


def test_doctor_single_extras_hint_has_no_combined_line(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _report(("mcp-extra-importable", install_hint("mcp")))
    monkeypatch.setattr(cli, "run_doctor", lambda **_kw: report)
    out = _ANSI.sub("", CliRunner().invoke(app, ["doctor"]).output)
    assert "서로를 지운다" not in out


def test_dev_single_hint_is_not_counted_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    """dev 설치는 기본 extras(dev,mcp,tui)를 늘 적어 mcp·tui 안내가 같은 문자열이다 — 안내 하나는 한 건."""
    monkeypatch.setattr(im, "detect", lambda: InstallContext("dev", "/py", Path("/r/anvyc")))
    assert install_hint("mcp") == install_hint("textual")  # 전제: 두 키의 안내가 같다
    report = _report(("mcp-extra-importable", install_hint("mcp")))
    monkeypatch.setattr(cli, "run_doctor", lambda **_kw: report)
    out = _ANSI.sub("", CliRunner().invoke(app, ["doctor"]).output)
    assert "서로를 지운다" not in out
