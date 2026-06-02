"""anvyc project doctor 사람용 출력(_render_project_doctor) 가드.

project doctor 출력을 top-level `anvyc doctor` 와 동일 스타일(글리프 + 그룹 + verdict)로
통일한 뒤, 다음 보증을 검증한다:
  - message/suggestion 의 대괄호가 Rich markup 으로 먹히지 않음 (escape) — 구 Table
    렌더는 `[profile x]` 를 태그로 삼켜 사라지게 했다(실 버그). 회귀 lock.
  - 조치 필요(blocking) → 정보(info) 섹션 순서, critical → warning 정렬
  - blocking 만 remediation(→) 노출, info 는 미노출
  - runs 추적이 없으므로 verdict 에 '통과 check 롤업'(checks clean) 미노출
  - 적용 가능한 check 0건 → 짧은 안내, finding 섹션 없음
색강제(FORCE_COLOR) 환경 무관하게 안정적이도록 no_color Console 로 캡처한다.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from rich.console import Console

import anvyc.cli as cli
from anvyc.checks.base import CheckResult, Severity
from anvyc.core.project_doctor import ProjectDoctorReport

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _capture(report: ProjectDoctorReport, monkeypatch: pytest.MonkeyPatch, width: int = 200) -> str:
    buf = io.StringIO()
    monkeypatch.setattr(
        cli,
        "console",
        Console(file=buf, force_terminal=False, no_color=True, highlight=False, width=width),
    )
    cli._render_project_doctor(report)
    return _ANSI.sub("", buf.getvalue())


def test_brackets_survive_render(monkeypatch: pytest.MonkeyPatch) -> None:
    # 구 Table 렌더가 삼키던 `[profile x]` 가 escape 로 살아남아야 한다(실 버그 회귀 lock).
    report = ProjectDoctorReport(
        path=Path("/tmp/proj"),
        results=[
            CheckResult(
                check_name="aws_profile_defined",
                severity=Severity.WARNING,
                message=".envrc AWS_PROFILE=foo 가 ~/.aws/config 에 정의 안 됨",
                suggestion="~/.aws/config 에 [profile foo] section 추가",
            )
        ],
    )
    out = _capture(report, monkeypatch)
    assert "[profile foo]" in out  # escape 누락 시 ' section 추가' 로 깨짐


def test_sections_and_severity_ordering(monkeypatch: pytest.MonkeyPatch) -> None:
    report = ProjectDoctorReport(
        path=Path("/tmp/proj"),
        results=[
            CheckResult("info_check", Severity.INFO, "info ok"),
            CheckResult("crit_check", Severity.CRITICAL, "crit msg"),
            CheckResult("warn_check", Severity.WARNING, "warn msg"),
        ],
    )
    out = _capture(report, monkeypatch)
    assert "조치 필요" in out
    assert "정보" in out
    # 조치 필요(critical→warning) 가 정보 앞, 그 안에서 critical 이 warning 앞.
    assert out.index("crit msg") < out.index("warn msg") < out.index("info ok")


def test_blocking_remediation_gating(monkeypatch: pytest.MonkeyPatch) -> None:
    report = ProjectDoctorReport(
        path=Path("/tmp/proj"),
        results=[
            CheckResult("c1", Severity.CRITICAL, "crit", suggestion="fix-crit"),
            CheckResult("c2", Severity.INFO, "info", suggestion="info-hint"),
        ],
    )
    out = _capture(report, monkeypatch)
    assert "→ fix-crit" in out  # blocking 은 remediation 노출
    assert "info-hint" not in out  # info 는 미노출


def test_no_checks_clean_rollup(monkeypatch: pytest.MonkeyPatch) -> None:
    # project doctor 는 runs 추적이 없어 '통과 check 롤업'(checks clean)을 쓰지 않는다.
    report = ProjectDoctorReport(
        path=Path("/tmp/proj"),
        results=[CheckResult("c1", Severity.INFO, "ok")],
    )
    out = _capture(report, monkeypatch)
    assert "checks clean" not in out
    assert "project doctor" in out  # 제목은 노출
    assert "ℹ 1 info" in out  # verdict bucket 은 노출


def test_empty_results_short_message(monkeypatch: pytest.MonkeyPatch) -> None:
    report = ProjectDoctorReport(path=Path("/tmp/proj"), results=[])
    out = _capture(report, monkeypatch)
    assert "적용 가능한 check 없음" in out
    assert "조치 필요" not in out
    assert "정보" not in out


def test_long_path_and_message_not_hard_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    # 좁은 폭에서도 긴 path(제목)·message 가 하드 개행되지 않아야 한다(soft_wrap).
    long_path = "/Users/edward/dev/some/very/deeply/nested/project/root/that/exceeds/forty/cols"
    long_msg = "this project doctor finding message is intentionally much wider than forty columns"
    report = ProjectDoctorReport(
        path=Path(long_path),
        results=[CheckResult("c1", Severity.WARNING, long_msg, suggestion="do something")],
    )
    out = _capture(report, monkeypatch, width=40)
    assert long_path in out
    assert long_msg in out
