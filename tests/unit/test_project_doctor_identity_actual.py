"""gh_identity_actual — 선언된 gh 계정과 프로필 토큰의 실체 대조."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.checks.base import Severity
from anvyc.core import project_doctor


def _project(tmp_path: Path, account: str) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".envrc").write_text(
        f'export GH_CONFIG_DIR="$HOME/.config/gh-{account}"\n', encoding="utf-8"
    )
    return proj


def _result(report, name: str):
    return next((r for r in report.results if r.check_name == name), None)


def test_actual_matches_declared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(project_doctor.identity_probe, "gh_login", lambda d: "16bitdo")
    report = project_doctor.run_project_doctor(_project(tmp_path, "16bitdo"))
    res = _result(report, "gh_identity_actual")
    assert res is not None
    assert res.severity is Severity.INFO


def test_actual_differs_is_critical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-08-12 실측 회귀 케이스 — gh-16bitdo 프로필의 토큰이 heisgone 이었다."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(project_doctor.identity_probe, "gh_login", lambda d: "heisgone")
    report = project_doctor.run_project_doctor(_project(tmp_path, "16bitdo"))
    res = _result(report, "gh_identity_actual")
    assert res is not None
    assert res.severity is Severity.CRITICAL
    assert "heisgone" in res.message and "16bitdo" in res.message
    assert report.has_blocking()


def test_probe_failure_is_info_not_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """조회 실패는 모름이지 불일치가 아니다 — 인프라 부재에 fail-closed 를 적용하지 않는다."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(project_doctor.identity_probe, "gh_login", lambda d: None)
    report = project_doctor.run_project_doctor(_project(tmp_path, "16bitdo"))
    res = _result(report, "gh_identity_actual")
    assert res is not None
    assert res.severity is Severity.INFO
    assert not report.has_blocking()


def test_no_gh_account_is_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = tmp_path / "bare"
    proj.mkdir()
    (proj / ".envrc").write_text('export FOO="bar"\n', encoding="utf-8")
    report = project_doctor.run_project_doctor(proj)
    assert _result(report, "gh_identity_actual") is None


# ---------------------------------------------------------------------------
# 위 4개는 gh_login 을 인자 무관 고정값으로 대체하는 mock 이라, "무엇이 실제로
# gh_login/probe_cached 에 전달되는가"의 회귀는 못 잡는다(리뷰 mutation C·D 실증:
# expand_envrc_path 를 Path.expanduser() 로, source=.../"hosts.yml" 을
# source=expanded_dir 로 되돌려도 위 4개는 전부 통과). 아래 2개는 spy 로 실제
# 전달값을 기록해 그 두 회귀를 직접 잡는다.
# ---------------------------------------------------------------------------


def test_gh_login_receives_expanded_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gh_login 에 전달되는 인자가 리터럴 '$HOME' 이 아니라 확장된 절대경로여야 한다.

    2026-08-12 Step 5 실측 회귀: `gh_config_dir_for_account()` 는 `.envrc` 에 쓸
    리터럴 `"$HOME/..."` 문자열을 돌려준다(direnv 가 셸에서 확장하는 것을 전제).
    이를 `expand_envrc_path()` 없이 `Path(config_dir).expanduser()` 로만 처리하면
    `expanduser()` 는 선행 `~` 만 확장하고 `$HOME` 리터럴은 그대로 두므로, subprocess
    의 `GH_CONFIG_DIR` 이 존재하지 않는 상대경로가 되어 `gh api` 호출이 항상 실패
    한다 — 즉 `gh_identity_actual` 이 프로덕션에서 절대 CRITICAL 을 낼 수 없는
    상태로 조용히 회귀한다.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    received: list[object] = []

    def spy_gh_login(config_dir: object) -> str:
        received.append(config_dir)
        return "16bitdo"

    monkeypatch.setattr(project_doctor.identity_probe, "gh_login", spy_gh_login)
    project_doctor.run_project_doctor(_project(tmp_path, "16bitdo"))

    assert len(received) == 1, f"gh_login 이 {len(received)}회 호출됨 (기대 1회)"
    passed = received[0]
    assert "$HOME" not in str(passed), f"$HOME 리터럴이 미확장 상태로 전달됨: {passed!r}"
    assert Path(str(passed)).is_absolute(), f"절대경로가 아님: {passed!r}"
    assert Path(str(passed)) == Path.home() / ".config" / "gh-16bitdo"


def test_probe_cached_source_is_hosts_file_not_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`probe_cached` 의 `source` 가 디렉터리가 아니라 `hosts.yml` 파일이어야 한다.

    회귀: `source` 를 gh config 디렉터리 자체로 주면, POSIX 에서 디렉터리 mtime 은
    엔트리 추가·삭제·rename 에만 갱신되고 기존 파일의 in-place 수정(gh 재인증이
    `hosts.yml` 을 쓰는 방식)에는 반응하지 않는다(project_doctor.py 의 설계 판단 1,
    실측 확인). 그 결과 재인증 직후에도 캐시가 최대 TTL(8h) 동안 옛 신원을 유지한다
    — 무효화가 가장 필요한 순간에 실패한다.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(project_doctor.identity_probe, "gh_login", lambda d: "16bitdo")
    captured: dict[str, object] = {}

    def spy_probe_cached(**kwargs: object) -> str | None:
        captured.update(kwargs)
        return "16bitdo"

    monkeypatch.setattr(project_doctor.identity_cache, "probe_cached", spy_probe_cached)
    project_doctor.run_project_doctor(_project(tmp_path, "16bitdo"))

    assert "source" in captured, "probe_cached 가 source kwarg 없이 호출됨"
    source = captured["source"]
    assert source is not None
    assert Path(str(source)).name == "hosts.yml", (
        f"source 가 파일이 아님(디렉터리로 회귀): {source!r}"
    )
