"""doctor 기본 출력(_print_summary) 발견성 가드 (PR2).

Top findings 가 severity 내림차순으로 노출되고(심각 항목이 info noise 에 묻히지 않음),
blocking finding 은 remediation(suggestion)을 기본 출력에서 한 줄로 보여주는지 검증한다.
색강제(FORCE_COLOR) 환경 무관하게 안정적이도록 no_color Console 로 캡처한다.
"""

from __future__ import annotations

import io
import re

import pytest
from rich.console import Console

import anvyc.cli as cli
from anvyc.checks.base import CheckResult, Severity
from anvyc.core.doctor import DoctorReport

# FORCE_COLOR 강제 환경에서도 안정적이도록 SGR(ANSI) 코드를 제거하고 비교한다.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _capture_summary(report: DoctorReport, monkeypatch: pytest.MonkeyPatch) -> str:
    buf = io.StringIO()
    monkeypatch.setattr(
        cli,
        "console",
        Console(file=buf, force_terminal=False, no_color=True, highlight=False, width=200),
    )
    cli._print_summary(report)
    return _ANSI.sub("", buf.getvalue())


def test_severity_rank_ordering() -> None:
    assert (
        cli._severity_rank(Severity.CRITICAL)
        > cli._severity_rank(Severity.WARNING)
        > cli._severity_rank(Severity.INFO)
    )


def test_top_findings_sorted_severity_desc(monkeypatch: pytest.MonkeyPatch) -> None:
    report = DoctorReport(
        results=[
            CheckResult("c1", Severity.INFO, "info one"),
            CheckResult("c2", Severity.INFO, "info two"),
            CheckResult("c3", Severity.CRITICAL, "crit msg"),
            CheckResult("c4", Severity.WARNING, "warn msg"),
        ]
    )
    out = _capture_summary(report, monkeypatch)
    assert "Top findings:" in out
    # critical 이 warning 보다, warning 이 info 보다 먼저 노출돼야 한다.
    assert out.index("crit msg") < out.index("warn msg") < out.index("info one")


def test_blocking_findings_show_remediation(monkeypatch: pytest.MonkeyPatch) -> None:
    report = DoctorReport(
        results=[
            CheckResult("c1", Severity.CRITICAL, "crit msg", suggestion="fix-crit-now"),
            CheckResult("c2", Severity.WARNING, "warn msg", suggestion="brew install x"),
            CheckResult("c3", Severity.INFO, "info msg", suggestion="info-only-hint"),
        ]
    )
    out = _capture_summary(report, monkeypatch)
    # blocking(critical/warning) 은 remediation 노출.
    assert "→ fix-crit-now" in out
    assert "→ brew install x" in out
    # info 는 blocking 아님 → suggestion 미노출.
    assert "info-only-hint" not in out


def test_more_count_uses_total(monkeypatch: pytest.MonkeyPatch) -> None:
    results = [CheckResult(f"c{i}", Severity.INFO, f"m{i}") for i in range(8)]
    report = DoctorReport(results=results)
    out = _capture_summary(report, monkeypatch)
    assert "... and 3 more" in out  # 8 - 5 노출


def test_clean_report_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _capture_summary(DoctorReport(results=[]), monkeypatch)
    assert "clean" in out
    assert "Top findings" not in out


def _capture_summary_width(
    report: DoctorReport, monkeypatch: pytest.MonkeyPatch, width: int
) -> str:
    """좁은 폭 Console 로 캡처 — 비-TTY 80열 fallback 회귀(soft_wrap) 검증용."""
    buf = io.StringIO()
    monkeypatch.setattr(
        cli,
        "console",
        Console(file=buf, force_terminal=False, no_color=True, highlight=False, width=width),
    )
    cli._print_summary(report)
    return _ANSI.sub("", buf.getvalue())


def test_findings_not_hard_wrapped_on_narrow_width(monkeypatch: pytest.MonkeyPatch) -> None:
    # 폭(40)보다 훨씬 긴 message/suggestion 이 중간 개행 없이 한 줄로 유지돼야 한다.
    # soft_wrap 누락 시 Rich 가 단어 경계에 \n 을 삽입해 아래 substring 비교가 깨진다.
    long_msg = "this is a very long doctor finding message that exceeds forty columns wide"
    long_sug = "rotate the very long credential by running the documented remediation command now"
    report = DoctorReport(
        results=[CheckResult("c1", Severity.CRITICAL, long_msg, suggestion=long_sug)]
    )
    out = _capture_summary_width(report, monkeypatch, width=40)
    assert long_msg in out  # 하드 개행이 삽입되면 통째 substring 매칭 실패
    assert long_sug in out
