"""gh_identity_actual — 선언된 gh 계정과 프로필 토큰의 실체 대조."""
from __future__ import annotations

import os
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


def test_probe_cached_source_is_collection_of_sibling_hosts_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`probe_cached` 의 `source` 가 이 프로필 하나가 아니라 형제 gh 프로필 전체의
    `hosts.yml` 집합이어야 한다 (디렉터리도 아니고, 자기 자신 하나도 아니다).

    회귀 1(라운드 1): `source` 를 gh config 디렉터리 자체로 주면 POSIX 에서 디렉터리
    mtime 이 파일 in-place 수정에 무반응이라 무효화를 놓친다(mutation D 로 검출력
    확보됨).
    회귀 2(이번 라운드): "이 프로필의 hosts.yml 하나만" 도 부족하다 — gh 는 토큰을
    OS 키체인에 저장해 모든 `gh-*` 프로필이 공유한다(2026-08-12 재실측). 형제
    프로필에서 재인증하면 이 프로필의 hosts.yml 은 안 바뀐 채로 실체만 바뀐다.
    `source` 는 부모 디렉터리의 `gh*/hosts.yml` 전체(자기 자신 포함)여야 한다.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(project_doctor.identity_probe, "gh_login", lambda d: "16bitdo")
    # 형제 프로필 2개(16bitdo 자신 + heisgone)를 실제로 만들어, glob 이 정말로
    # 부모 디렉터리 아래 gh* 전체를 찾는지(자기 자신만이 아니라) 확인한다.
    gh_root = tmp_path / "home" / ".config"
    for account in ("16bitdo", "heisgone"):
        d = gh_root / f"gh-{account}"
        d.mkdir(parents=True)
        (d / "hosts.yml").write_text("users: {}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def spy_probe_cached(**kwargs: object) -> str | None:
        captured.update(kwargs)
        return "16bitdo"

    monkeypatch.setattr(project_doctor.identity_cache, "probe_cached", spy_probe_cached)
    project_doctor.run_project_doctor(_project(tmp_path, "16bitdo"))

    assert "source" in captured, "probe_cached 가 source kwarg 없이 호출됨"
    sources = list(captured["source"])
    assert len(sources) == 2, f"형제 프로필을 전부 못 모음: {sources!r}"
    names = sorted(Path(str(s)).name for s in sources)
    assert names == ["hosts.yml", "hosts.yml"], f"디렉터리가 섞여 있음: {sources!r}"
    parent_names = sorted(Path(str(s)).parent.name for s in sources)
    assert parent_names == ["gh-16bitdo", "gh-heisgone"], (
        f"자기 자신만 또는 다른 형제만 모음: {sources!r}"
    )


def test_sibling_profile_reauth_invalidates_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """다른 gh 프로필의 재인증이 이 프로필의 캐시도 무효화해야 한다 — 핵심 회귀 테스트.

    2026-08-12 재실측 회귀: gh 는 토큰을 OS 키체인에 저장해 모든 `gh-*` 프로필이
    공유한다. `gh-heisgone` 에서 재로그인하면 `gh-16bitdo` 프로필의 `gh api user`
    응답도 `heisgone` 으로 바뀌는데, `gh-16bitdo` 자신의 `hosts.yml` 은 바뀌지 않는다.
    "이 프로필의 hosts.yml 만" 감시하는 캐시는 이 순간 거짓 음성(여전히 16bitdo 로
    판정)을 낸다 — 하필 이 check 가 잡아야 하는 바로 그 순간에. `gh_login` 을
    "키체인이 공유하는 전역 상태"를 흉내 내는 fake 로 대체해(어느 프로필에서
    조회하든 같은 값을 반환) 재현한다.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    gh_root = tmp_path / "home" / ".config"
    own_hosts = gh_root / "gh-16bitdo" / "hosts.yml"
    own_hosts.parent.mkdir(parents=True)
    own_hosts.write_text("users:\n  16bitdo: {}\n", encoding="utf-8")
    sibling_hosts = gh_root / "gh-heisgone" / "hosts.yml"
    sibling_hosts.parent.mkdir(parents=True)
    sibling_hosts.write_text("users:\n  heisgone: {}\n", encoding="utf-8")

    shared_keychain = ["16bitdo"]  # 모든 프로필이 공유하는 "실제" 신원
    calls: list[int] = []

    def fake_gh_login(_config_dir: object) -> str:
        calls.append(1)
        return shared_keychain[0]

    monkeypatch.setattr(project_doctor.identity_probe, "gh_login", fake_gh_login)
    proj = _project(tmp_path, "16bitdo")

    report1 = project_doctor.run_project_doctor(proj)
    res1 = _result(report1, "gh_identity_actual")
    assert res1.severity is Severity.INFO
    assert len(calls) == 1

    # gh-heisgone 에서 재인증 발생을 흉내: 그 프로필의 hosts.yml mtime 만 바뀌고,
    # 우리가 선언한 gh-16bitdo/hosts.yml 은 그대로다. 그런데 공유 키체인(가짜)의
    # 실체는 이미 바뀌어 있다 — 실제 세계에서 재인증이 어느 프로필의 hosts.yml 을
    # 갱신하는지는 2026-08-12 실측(15:40:54)으로 확인된 사실.
    shared_keychain[0] = "heisgone"
    bumped = sibling_hosts.stat().st_mtime + 5
    os.utime(sibling_hosts, (bumped, bumped))

    report2 = project_doctor.run_project_doctor(proj)
    res2 = _result(report2, "gh_identity_actual")
    assert res2.severity is Severity.CRITICAL, (
        f"형제 프로필 재인증을 캐시가 놓침 — severity={res2.severity}, "
        f"message={res2.message!r}"
    )
    assert "heisgone" in res2.message and "16bitdo" in res2.message
    assert len(calls) == 2, "캐시가 무효화되지 않아 재조회가 안 일어남"
