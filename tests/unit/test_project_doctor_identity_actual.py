"""gh_identity_actual — 선언된 gh 계정과 프로필 토큰의 실체 대조."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from anvyc.checks.base import CheckResult, Severity
from anvyc.core import account_manifest, identity_cache, identity_probe, project_doctor


def _project(tmp_path: Path, account: str) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".envrc").write_text(
        f'export GH_CONFIG_DIR="$HOME/.config/gh-{account}"\n', encoding="utf-8"
    )
    return proj


def _result(report: project_doctor.ProjectDoctorReport, name: str) -> CheckResult | None:
    return next((r for r in report.results if r.check_name == name), None)


def test_actual_matches_declared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "16bitdo")
    report = project_doctor.run_project_doctor(_project(tmp_path, "16bitdo"))
    res = _result(report, "gh_identity_actual")
    assert res is not None
    assert res.severity is Severity.INFO


def test_actual_differs_is_critical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-08-12 실측 회귀 케이스 — gh-16bitdo 프로필의 토큰이 heisgone 이었다."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "heisgone")
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
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: None)
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

    monkeypatch.setattr(identity_probe, "gh_login", spy_gh_login)
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
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "16bitdo")
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

    monkeypatch.setattr(identity_cache, "probe_cached", spy_probe_cached)
    project_doctor.run_project_doctor(_project(tmp_path, "16bitdo"))

    assert "source" in captured, "probe_cached 가 source kwarg 없이 호출됨"
    sources = list(captured["source"])  # type: ignore[call-overload]
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

    monkeypatch.setattr(identity_probe, "gh_login", fake_gh_login)
    proj = _project(tmp_path, "16bitdo")

    report1 = project_doctor.run_project_doctor(proj)
    res1 = _result(report1, "gh_identity_actual")
    assert res1 is not None
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
    assert res2 is not None
    assert res2.severity is Severity.CRITICAL, (
        f"형제 프로필 재인증을 캐시가 놓침 — severity={res2.severity}, "
        f"message={res2.message!r}"
    )
    assert "heisgone" in res2.message and "16bitdo" in res2.message
    assert len(calls) == 2, "캐시가 무효화되지 않아 재조회가 안 일어남"


# ---------------------------------------------------------------------------
# C1 (최종 리뷰 Critical) — 비교 대상이 `.envrc` 라벨이 아니라 manifest ownership.
#
# 위 테스트들은 전부 "`.envrc` 라벨 == 실체?" 만 검증한다 — 라벨 자신과 실체를
# 비교하므로 `.envrc` 가 통째로 다른 계정으로 드리프트하면 그 계정 프로필을 조회해
# 그 계정을 얻고 "일치(INFO)" 를 낸다. 게이트가 스스로를 무력화한다. 판정 기준(SoT)
# 은 L1 manifest 의 ownership 이고 `.envrc` 는 머신 로컬 라벨일 뿐이다.
# ---------------------------------------------------------------------------

_PROJECTS = """
version: 1
projects:
  - id: analysis
    repo: 16bitdo/analysis
    ownership: personal-16bitdo
"""
_BINDINGS = """
version: 1
machine: test-machine
accounts:
  personal-16bitdo:
    github_login: 16bitdo
    commit_email: 16bitdo@gmail.com
    gh_config_dir: ~/.config/gh-16bitdo
"""
_BINDINGS_NO_GH_LOGIN = """
version: 1
machine: test-machine
accounts:
  personal-16bitdo:
    commit_email: 16bitdo@gmail.com
"""


def _routed_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    envrc_account: str,
    slug: str = "16bitdo/analysis",
    bindings: str = _BINDINGS,
) -> Path:
    """manifest(L1) + `.envrc` 라벨을 **따로** 지정할 수 있는 저장소 fixture.

    둘을 갈라놓을 수 있어야 "무엇과 비교하는가" 를 검증할 수 있다 — 기존
    `_project()` 는 manifest 자체가 없어 라벨 == 기대값이 되어 구분이 불가능하다.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    m = tmp_path / "account-routing.yaml"
    m.write_text(_PROJECTS, encoding="utf-8")
    b = tmp_path / "binds"
    b.mkdir()
    (b / "bindings.test-machine.yaml").write_text(bindings, encoding="utf-8")
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(m))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(b))
    monkeypatch.setattr(account_manifest, "machine_name", lambda: "test-machine")
    # commit_identity_actual 은 이 테스트들의 관심사가 아니다 — 실제 git 호출로
    # 새어나가 결과가 머신 상태에 의존하지 않도록 고정한다.
    monkeypatch.setattr(
        identity_probe, "commit_email", lambda p: "16bitdo@gmail.com"
    )

    proj = tmp_path / "analysis"
    (proj / ".git").mkdir(parents=True)
    (proj / ".git" / "config").write_text(
        f'[remote "origin"]\n\turl = git@github.com:{slug}.git\n', encoding="utf-8"
    )
    (proj / ".envrc").write_text(
        f'export GH_CONFIG_DIR="$HOME/.config/gh-{envrc_account}"\n', encoding="utf-8"
    )
    return proj


def test_envrc_drift_alone_reproduces_the_gate_bypass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C1 재현 — ownership≠라벨 ∧ 실체==라벨 이면 CRITICAL 이어야 한다.

    manifest 는 `16bitdo/analysis` 를 `personal-16bitdo`(github_login=16bitdo) 소유로
    선언했는데 `.envrc` 만 `gh-heisgone` 으로 드리프트한 상태. 라벨끼리 비교하면
    heisgone 프로필을 조회해 heisgone 을 얻고 라벨 heisgone 과 같으므로 **INFO(정상)**
    가 나온다 — 잘못된 계정으로 `gh pr create` 가 통과한다. 이 브랜치가 막으려던
    사고가 `.envrc` 파일 한 줄의 드리프트만으로 재현된다.
    """
    proj = _routed_repo(tmp_path, monkeypatch, envrc_account="heisgone")
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "heisgone")

    report = project_doctor.run_project_doctor(proj)
    res = _result(report, "gh_identity_actual")
    assert res is not None
    assert res.severity is Severity.CRITICAL, (
        "ownership(16bitdo)과 실체(heisgone)가 다른데 `.envrc` 라벨(heisgone)과만 "
        f"비교해 통과시킴 — severity={res.severity}, message={res.message!r}"
    )
    assert report.has_blocking()


def test_critical_message_distinguishes_probed_actual_and_expected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """불일치 메시지가 세 값을 **구분해** 보여야 한다 — 조회 프로필 / 실체 / 기대.

    세 값이 전부 다른 상황을 만들어(라벨 heisgone · 실체 thirdparty · ownership
    16bitdo) 어느 하나라도 메시지에서 빠지면 사용자가 무엇을 고쳐야 할지 알 수 없게
    되는 것을 잡는다. 기대의 출처(manifest / `.envrc` 폴백)도 드러나야 한다.
    """
    proj = _routed_repo(tmp_path, monkeypatch, envrc_account="heisgone")
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "thirdparty")

    res = _result(project_doctor.run_project_doctor(proj), "gh_identity_actual")
    assert res is not None and res.severity is Severity.CRITICAL
    assert "heisgone" in res.message, f"조회한 프로필(.envrc 라벨) 누락: {res.message!r}"
    assert "thirdparty" in res.message, f"실체 누락: {res.message!r}"
    assert "16bitdo" in res.message, f"기대(ownership) 누락: {res.message!r}"
    assert "manifest" in res.message, f"기대의 출처가 안 드러남: {res.message!r}"


def test_actual_matching_ownership_is_not_critical_despite_label_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ownership == 실체면 `.envrc` 라벨만 달라도 CRITICAL 이 아니다.

    라벨은 어느 프로필을 **조회할지**만 정한다. gh 는 토큰을 OS 키체인에 공유하므로
    라벨이 밀려 있어도 실체가 ownership 과 같을 수 있다 — 신원 자체는 옳으므로
    커밋/PR 을 막을 이유가 없다. 라벨 드리프트는 `gh_account_routing` 의 몫이다.
    """
    proj = _routed_repo(tmp_path, monkeypatch, envrc_account="heisgone")
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "16bitdo")

    report = project_doctor.run_project_doctor(proj)
    res = _result(report, "gh_identity_actual")
    assert res is not None
    assert res.severity is Severity.INFO, (
        f"ownership(16bitdo)==실체(16bitdo)인데 차단함 — message={res.message!r}"
    )
    assert not report.has_blocking()


def test_probe_target_stays_the_envrc_label_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**조회 위치**는 ownership 이 아니라 `.envrc` 라벨 프로필 그대로여야 한다.

    비교 대상만 ownership 으로 옮기는 것이 C1 수정의 핵심이다. 조회 위치까지
    ownership 으로 바꾸면 "지금 이 프로젝트에서 실제로 쓰일 프로필"(드리프트한
    gh-heisgone)을 아예 안 보게 되어 검출 자체가 사라진다 — 게이트가 항상 통과하는
    더 나쁜 상태가 된다.
    """
    proj = _routed_repo(tmp_path, monkeypatch, envrc_account="heisgone")
    received: list[object] = []

    def spy_gh_login(config_dir: object) -> str:
        received.append(config_dir)
        return "heisgone"

    monkeypatch.setattr(identity_probe, "gh_login", spy_gh_login)
    project_doctor.run_project_doctor(proj)

    assert len(received) == 1, f"gh_login 이 {len(received)}회 호출됨 (기대 1회)"
    assert Path(str(received[0])) == Path.home() / ".config" / "gh-heisgone", (
        f"조회 대상이 `.envrc` 라벨 프로필이 아님: {received[0]!r}"
    )


def test_unregistered_repo_falls_back_to_envrc_label_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """manifest 미등록 저장소는 기존 `.envrc` 폴백 동작을 유지한다 (불일치 → CRITICAL)."""
    proj = _routed_repo(tmp_path, monkeypatch, envrc_account="16bitdo", slug="someone/other")
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "heisgone")

    res = _result(project_doctor.run_project_doctor(proj), "gh_identity_actual")
    assert res is not None and res.severity is Severity.CRITICAL
    assert ".envrc" in res.message, f"폴백 출처가 안 드러남: {res.message!r}"


def test_unregistered_repo_falls_back_to_envrc_label_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """manifest 미등록 + 라벨==실체 → 기존대로 INFO (폴백이 과차단하지 않는다)."""
    proj = _routed_repo(tmp_path, monkeypatch, envrc_account="16bitdo", slug="someone/other")
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "16bitdo")

    report = project_doctor.run_project_doctor(proj)
    res = _result(report, "gh_identity_actual")
    assert res is not None and res.severity is Severity.INFO
    assert not report.has_blocking()


def test_declared_but_unbound_machine_falls_back_to_envrc_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """선언은 있으나 이 머신 바인딩에 `github_login` 이 없으면 라벨로 폴백한다.

    `resolve()` 는 이 경우 `ownership_id` 만 채운 부분 결과를 준다 — `resolved is not
    None` 만 보고 `github_login=None` 을 기대값으로 삼으면 실체와 절대 같아질 수 없어
    항상 CRITICAL 이 되는 오탐 차단이 된다.
    """
    proj = _routed_repo(
        tmp_path, monkeypatch, envrc_account="16bitdo", bindings=_BINDINGS_NO_GH_LOGIN
    )
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "16bitdo")

    report = project_doctor.run_project_doctor(proj)
    res = _result(report, "gh_identity_actual")
    assert res is not None and res.severity is Severity.INFO
    assert not report.has_blocking()


def test_probe_failure_is_info_even_with_manifest_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """조회 실패는 manifest 선언이 있어도 INFO — 모름에 fail-closed 를 적용하지 않는다."""
    proj = _routed_repo(tmp_path, monkeypatch, envrc_account="heisgone")
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: None)

    report = project_doctor.run_project_doctor(proj)
    res = _result(report, "gh_identity_actual")
    assert res is not None and res.severity is Severity.INFO
    assert not report.has_blocking()


def test_manifest_loaded_once_per_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """orchestrator 가 manifest 를 한 번만 로드해 check 들에 내려준다.

    check 마다 `account_manifest.resolve()` 를 다시 부르면 훅이 Bash 명령마다 호출하는
    경로에서 YAML 파싱이 배수로 늘어난다 — C1 수정으로 소비처가 하나 더 늘었으므로
    회귀 여지가 커졌다.
    """
    proj = _routed_repo(tmp_path, monkeypatch, envrc_account="16bitdo")
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "16bitdo")
    calls: list[str] = []
    real_resolve = account_manifest.resolve

    def counting_resolve(slug: str) -> account_manifest.ResolvedAccount | None:
        calls.append(slug)
        return real_resolve(slug)

    monkeypatch.setattr(account_manifest, "resolve", counting_resolve)
    project_doctor.run_project_doctor(proj)

    assert calls == ["16bitdo/analysis"], f"manifest 를 {len(calls)}회 로드함: {calls}"
