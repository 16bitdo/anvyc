"""doctor 출력(_print_summary / _print_verbose) 발견성·가독성 가드.

claude doctor 스타일 재설계(DESIGN.md §27.3.5) 후에도 다음 보증이 유지되는지 검증한다:
  - severity 내림차순 노출 (심각 항목이 info noise 에 묻히지 않음)
  - blocking finding 만 remediation(suggestion)을 기본 출력에 노출 (info 는 미노출)
  - 그룹당 cap 초과분은 "+N more" 로 접되 남은 건수가 정확
  - clean 리포트는 짧게 단락 (finding 섹션 없음)
  - 비-TTY 80열 fallback 에서도 message/suggestion 이 하드 개행되지 않음 (soft_wrap)
  - message/suggestion 의 대괄호가 Rich markup 으로 먹히지 않음 (escape)
  - verbose 체크리스트가 통과 check 를 ✓ 로, finding 보유 check 를 글리프+건수로 노출
색강제(FORCE_COLOR) 환경 무관하게 안정적이도록 no_color Console 로 캡처한다.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable

import pytest
from rich.console import Console

import anvyc.cli as cli
from anvyc.checks.base import CheckResult, Severity
from anvyc.core.doctor import CheckRun, DoctorReport

# FORCE_COLOR 강제 환경에서도 안정적이도록 SGR(ANSI) 코드를 제거하고 비교한다.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _capture(
    fn: Callable[[DoctorReport], None],
    report: DoctorReport,
    monkeypatch: pytest.MonkeyPatch,
    width: int = 200,
) -> str:
    buf = io.StringIO()
    monkeypatch.setattr(
        cli,
        "console",
        Console(file=buf, force_terminal=False, no_color=True, highlight=False, width=width),
    )
    fn(report)
    return _ANSI.sub("", buf.getvalue())


def _capture_summary(report: DoctorReport, monkeypatch: pytest.MonkeyPatch, width: int = 200) -> str:
    return _capture(cli._print_summary, report, monkeypatch, width)


def _capture_verbose(report: DoctorReport, monkeypatch: pytest.MonkeyPatch) -> str:
    return _capture(cli._print_verbose, report, monkeypatch)


def test_severity_rank_ordering() -> None:
    assert (
        cli._severity_rank(Severity.CRITICAL)
        > cli._severity_rank(Severity.WARNING)
        > cli._severity_rank(Severity.INFO)
    )


def test_findings_sorted_severity_desc(monkeypatch: pytest.MonkeyPatch) -> None:
    # critical → warning → info 순으로 노출돼야 한다 (조치 필요 섹션이 정보 섹션보다 앞).
    report = DoctorReport(
        results=[
            CheckResult("c1", Severity.INFO, "info one"),
            CheckResult("c2", Severity.INFO, "info two"),
            CheckResult("c3", Severity.CRITICAL, "crit msg"),
            CheckResult("c4", Severity.WARNING, "warn msg"),
        ]
    )
    out = _capture_summary(report, monkeypatch)
    assert "조치 필요" in out  # blocking 섹션 헤더
    assert "정보" in out  # info 섹션 헤더
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


def test_group_truncation_caps_examples(monkeypatch: pytest.MonkeyPatch) -> None:
    # 단일 check 의 finding 이 cap 을 넘으면 cap 개만 노출 + "+N more" 로 남은 건수 정확.
    cap = cli._SUMMARY_GROUP_CAP
    n = cap + 5
    results = [CheckResult("noisy-check", Severity.INFO, f"m{i}") for i in range(n)]
    report = DoctorReport(results=results)
    out = _capture_summary(report, monkeypatch)
    assert f"+{n - cap} more" in out  # 남은 건수 = total - cap
    assert "m0" in out  # 앞쪽은 노출
    assert f"m{n - 1}" not in out  # 잘린 뒤쪽은 미노출
    assert "noisy-check" in out  # 그룹 헤더는 check 이름
    assert f"({n})" in out  # 그룹 헤더에 전체 건수 표기


def test_clean_report_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _capture_summary(DoctorReport(results=[]), monkeypatch)
    assert "clean" in out
    assert "조치 필요" not in out
    assert "정보" not in out


def test_header_shows_severity_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    # verdict 한 줄에 critical/warning/info 3 bucket 카운트가 노출돼야 한다.
    report = DoctorReport(
        results=[
            CheckResult("c1", Severity.CRITICAL, "x"),
            CheckResult("c2", Severity.WARNING_FOREIGN, "y"),
            CheckResult("c3", Severity.INFO, "z"),
            CheckResult("c4", Severity.INFO_ALIASED, "w"),
        ]
    )
    out = _capture_summary(report, monkeypatch)
    assert "1 critical" in out
    assert "1 warning" in out  # WARNING_FOREIGN 도 warning bucket 에 합산
    assert "2 info" in out  # INFO + INFO_ALIASED 합산


def test_clean_rollup_counts_passed_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    # runs 가 있으면 verdict 에 "통과 check 수 / 전체" 롤업이 노출돼야 한다.
    report = DoctorReport(
        results=[CheckResult("b", Severity.WARNING, "warn")],
        runs=[
            CheckRun("a", []),  # 통과
            CheckRun("b", [CheckResult("b", Severity.WARNING, "warn")]),  # finding 1건
            CheckRun("c", []),  # 통과
        ],
    )
    out = _capture_summary(report, monkeypatch)
    assert "2/3 checks clean" in out


def test_verbose_checklist_marks_pass_and_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    # verbose 는 실행된 모든 check 를 체크리스트로 — 통과는 ✓, finding 보유는 글리프+건수.
    report = DoctorReport(
        results=[CheckResult("b", Severity.WARNING, "warn msg", suggestion="do x")],
        runs=[
            CheckRun("passing-check", []),
            CheckRun("b", [CheckResult("b", Severity.WARNING, "warn msg", suggestion="do x")]),
        ],
    )
    out = _capture_verbose(report, monkeypatch)
    assert "검사 항목" in out  # 체크리스트 섹션 헤더
    assert "✓ passing-check" in out  # 통과 check
    assert "1 finding" in out  # finding 보유 check 의 건수
    assert "→ do x" in out  # verbose 도 remediation 노출


def test_findings_not_hard_wrapped_on_narrow_width(monkeypatch: pytest.MonkeyPatch) -> None:
    # 폭(40)보다 훨씬 긴 message/suggestion 이 중간 개행 없이 한 줄로 유지돼야 한다.
    # soft_wrap 누락 시 Rich 가 단어 경계에 \n 을 삽입해 아래 substring 비교가 깨진다.
    long_msg = "this is a very long doctor finding message that exceeds forty columns wide"
    long_sug = "rotate the very long credential by running the documented remediation command now"
    report = DoctorReport(
        results=[CheckResult("c1", Severity.CRITICAL, long_msg, suggestion=long_sug)]
    )
    out = _capture_summary(report, monkeypatch, width=40)
    assert long_msg in out  # 하드 개행이 삽입되면 통째 substring 매칭 실패
    assert long_sug in out


def test_suggestion_brackets_survive_render(monkeypatch: pytest.MonkeyPatch) -> None:
    # `pip install 'anvyc[cost-aws]'` 의 [cost-aws] 가 Rich markup 으로 먹히면
    # `'anvyc'` 로 깨져 사용자가 복붙해 실패한다(UnknownSourceError). escape 로
    # message/suggestion 의 대괄호가 렌더 후에도 리터럴로 살아있어야 한다.
    report = DoctorReport(
        results=[
            CheckResult(
                "cost-aws",
                Severity.WARNING,
                "AWS Cost Explorer adapter 비활성 (cost-aws optional dep)",
                suggestion="pip install 'anvyc[cost-aws]' (설치 후 anvyc cost collect --source aws)",
            ),
            CheckResult(
                "mcp",
                Severity.WARNING,
                "`mcp` 미설치 — [mcp] extra 필요",
                suggestion="pip install 'anvyc[mcp]'",
            ),
        ]
    )
    out = _capture_summary(report, monkeypatch)
    assert "anvyc[cost-aws]" in out  # escape 누락 시 'anvyc' 로 깨짐
    assert "anvyc[mcp]" in out
    assert "[mcp] extra" in out  # message 의 대괄호도 보존
