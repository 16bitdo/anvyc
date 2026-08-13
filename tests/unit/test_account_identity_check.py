"""global doctor account-identity-actual — anvyx C6 pre-run gate 가 소비한다."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.checks.account_identity import AccountIdentityActualCheck
from anvyc.checks.base import CheckContext, Severity
from anvyc.core import account_manifest, identity_cache, identity_probe

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


@pytest.fixture()
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = tmp_path / "account-routing.yaml"
    m.write_text(_PROJECTS, encoding="utf-8")
    b = tmp_path / "binds"
    b.mkdir()
    (b / "bindings.test-machine.yaml").write_text(_BINDINGS, encoding="utf-8")
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(m))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(b))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    # 브리프 원안은 HOME 을 고정하지 않아 gh_config_dir(~/.config/gh-16bitdo) 확장이
    # 실제 머신의 홈 디렉터리로 새서 진짜 ~/.config/gh-* 를 glob 하게 된다(비결정적 ·
    # 테스트 격리 위반). test_project_doctor_identity_actual.py 의 기존 관례(HOME
    # 격리)를 따라 고정한다.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(account_manifest, "machine_name", lambda: "test-machine")


def test_mismatch_is_critical(wired: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-08-12 실측 회귀 케이스 — gh-16bitdo 프로필의 토큰이 heisgone 이었다."""
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "heisgone")
    results = AccountIdentityActualCheck().run(CheckContext())
    assert any(r.severity is Severity.CRITICAL for r in results)
    crit = next(r for r in results if r.severity is Severity.CRITICAL)
    assert "heisgone" in crit.message and "16bitdo" in crit.message
    assert crit.location is not None
    # suggestion 은 raw 바인딩 값이 아니라 확장된 절대경로를 써야 한다 — raw 값이
    # `~` 로 시작하면 큰따옴표 안에서 셸이 확장하지 않아(bash/zsh 공통 동작) 복붙
    # 실행 시 깨진다(브리프 Step 4 원안의 버그: f'GH_CONFIG_DIR="{gh_dir}" ...').
    assert crit.suggestion is not None
    assert "~" not in crit.suggestion, f"suggestion 에 미확장 '~' 잔존: {crit.suggestion!r}"


def test_match_is_info(wired: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "16bitdo")
    results = AccountIdentityActualCheck().run(CheckContext())
    assert results and all(r.severity is Severity.INFO for r in results)


def test_no_manifest_is_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(tmp_path / "nope"))
    assert AccountIdentityActualCheck().run(CheckContext()) == []


def test_probe_failure_is_silent(wired: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """조회 실패(gh_login 이 None)는 "모름"이지 "불일치"가 아니다 — 보고하지 않는다.

    리뷰 I1 대응: global doctor 는 이 머신의 전 계정을 훑으므로, gh 일시
    장애·미인증·네트워크 문제만으로 결과를 냈다간 그게 그대로 summary.critical 을
    거쳐 anvyx C6 게이트의 오탐 차단(autopilot 전체 block)으로 이어진다 — "인프라
    부재에 fail-closed 를 적용하지 않는다"는 identity_probe.py 자체의 불변식이기도
    하다. 이 분기(run() 의 `if actual is None: continue`)를 지키는 회귀 테스트가
    이전엔 없었다(mutation D — "None 도 INFO 로 보고"하도록 바꿔도 기존 7개 전부
    통과했다).
    """
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: None)
    assert AccountIdentityActualCheck().run(CheckContext()) == []


def test_registered_in_doctor() -> None:
    """doctor._REGISTRY 등록 확인 — 기존 check 들(test_creds_expiry_check.py 등)과 동일 관례.

    이 check 은 anvyx C6 gate 가 소비하는 것이 **global** `anvyc doctor` 이지
    `anvyc project doctor` 가 아니라는 점이 핵심이라, 등록처가 doctor.py 의
    _REGISTRY 인지를 직접 잠근다.
    """
    from anvyc.core.doctor import _REGISTRY

    assert "account-identity-actual" in _REGISTRY
    assert _REGISTRY["account-identity-actual"].name == "account-identity-actual"


# ---------------------------------------------------------------------------
# 위 4개는 gh_login 을 인자 무관 고정값으로 대체하는 mock 이라, "무엇이 실제로
# gh_login/probe_cached 에 전달되는가"의 회귀는 못 잡는다
# (test_project_doctor_identity_actual.py 의 리뷰 I1 실증과 동일 계열 — mutation 으로
# expand_envrc_path 를 Path.expanduser() 로, source 를 단일 경로로 되돌려도 위
# 4개는 전부 통과했을 것). 아래는 spy 로 실제 전달값을 기록해 그 회귀를 직접 잡는다.
# ---------------------------------------------------------------------------


def test_gh_login_receives_expanded_absolute_path(
    wired: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gh_login 에 전달되는 인자가 raw 바인딩 값(`~/...`)이 아니라 확장된 절대경로여야 한다."""
    received: list[object] = []

    def spy_gh_login(config_dir: object) -> str:
        received.append(config_dir)
        return "16bitdo"

    monkeypatch.setattr(identity_probe, "gh_login", spy_gh_login)
    AccountIdentityActualCheck().run(CheckContext())

    assert len(received) == 1, f"gh_login 이 {len(received)}회 호출됨 (기대 1회)"
    passed = received[0]
    assert "~" not in str(passed), f"'~' 리터럴이 미확장 상태로 전달됨: {passed!r}"
    assert Path(str(passed)).is_absolute(), f"절대경로가 아님: {passed!r}"
    assert Path(str(passed)) == Path.home() / ".config" / "gh-16bitdo"


def test_gh_login_receives_expanded_path_for_dollar_home_style_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`$HOME/...` 표기 바인딩도 절대경로로 확장돼 전달돼야 한다 — `~` 전용 테스트로는 못 잡는 회귀.

    `Path(gh_dir).expanduser()` 는 `~` 는 (우연히) 제대로 확장하지만 `$HOME` 리터럴은
    그대로 둔다 — Task 4 에서 gh_identity_actual 이 이 정확한 조건으로 회귀해 probe 가
    항상 실패했다(기능이 조용히 죽은 채 테스트만 통과). `~` 바인딩만 쓰는
    `wired` fixture 로는 이 회귀를 재현할 수 없어 별도 바인딩으로 검증한다.
    """
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    m = tmp_path / "account-routing.yaml"
    m.write_text(_PROJECTS, encoding="utf-8")
    b = tmp_path / "binds"
    b.mkdir()
    (b / "bindings.test-machine.yaml").write_text(
        "version: 1\n"
        "machine: test-machine\n"
        "accounts:\n"
        "  personal-16bitdo:\n"
        "    github_login: 16bitdo\n"
        "    gh_config_dir: $HOME/.config/gh-16bitdo\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(m))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(b))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(account_manifest, "machine_name", lambda: "test-machine")

    received: list[object] = []

    def spy_gh_login(config_dir: object) -> str:
        received.append(config_dir)
        return "16bitdo"

    monkeypatch.setattr(identity_probe, "gh_login", spy_gh_login)
    AccountIdentityActualCheck().run(CheckContext())

    assert len(received) == 1, f"gh_login 이 {len(received)}회 호출됨 (기대 1회)"
    passed = received[0]
    assert "$HOME" not in str(passed), f"'$HOME' 리터럴이 미확장 상태로 전달됨: {passed!r}"
    assert Path(str(passed)) == fake_home / ".config" / "gh-16bitdo"


def test_probe_cached_source_is_sibling_hosts_files_not_single_path(
    wired: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`probe_cached` 의 `source` 가 이 프로필 하나가 아니라 형제 gh 프로필 전체의
    `hosts.yml` 집합이어야 한다 (디렉터리 자체도 아니고, 자기 자신 하나도 아니다).

    2026-08-12 실측 — gh CLI 는 GH_CONFIG_DIR 로 라벨(계정 표시)만 프로필별로
    나누고 토큰은 OS 키체인에 저장해 모든 gh-* 프로필이 공유한다. `source` 를
    단일 경로(gh_config_dir 자체 또는 자기 hosts.yml 하나)로 되돌리면 형제 프로필
    재인증으로 실체가 바뀌어도 캐시가 무효화되지 않는다 — 이 테스트가 그 되돌림을
    잡는다(project_doctor._gh_profile_hosts_files 재사용이 실제로 배선됐는지 확인).
    """
    gh_root = Path.home() / ".config"
    for account in ("16bitdo", "heisgone"):
        d = gh_root / f"gh-{account}"
        d.mkdir(parents=True)
        (d / "hosts.yml").write_text("users: {}\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def spy_probe_cached(**kwargs: object) -> str | None:
        captured.update(kwargs)
        return "16bitdo"

    monkeypatch.setattr(identity_cache, "probe_cached", spy_probe_cached)
    AccountIdentityActualCheck().run(CheckContext())

    assert "source" in captured, "probe_cached 가 source kwarg 없이 호출됨"
    sources = list(captured["source"])  # type: ignore[call-overload]
    assert len(sources) == 2, f"형제 프로필을 전부 못 모음: {sources!r}"
    names = sorted(Path(str(s)).name for s in sources)
    assert names == ["hosts.yml", "hosts.yml"], f"디렉터리가 섞여 있음: {sources!r}"
    parent_names = sorted(Path(str(s)).parent.name for s in sources)
    assert parent_names == ["gh-16bitdo", "gh-heisgone"], (
        f"자기 자신만 또는 다른 형제만 모음: {sources!r}"
    )


# ---------------------------------------------------------------------------
# 신원 값 정규화 배선 — 이 check 은 resolve() 를 거치지 않고 바인딩을 직접 읽는다.
# 세 비교 지점이 같은 규칙을 쓰지 않으면 같은 바인딩이 check 마다 다르게 판정된다.
# ---------------------------------------------------------------------------


def _wire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bindings: str) -> None:
    m = tmp_path / "account-routing.yaml"
    m.write_text(_PROJECTS, encoding="utf-8")
    b = tmp_path / "binds"
    b.mkdir()
    (b / "bindings.test-machine.yaml").write_text(bindings, encoding="utf-8")
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(m))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(b))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(account_manifest, "machine_name", lambda: "test-machine")


def test_case_difference_in_binding_is_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """바인딩 `16BitDo`, 실체 `16bitdo` — 같은 계정이므로 CRITICAL 이 아니다."""
    _wire(
        tmp_path,
        monkeypatch,
        "version: 1\n"
        "machine: test-machine\n"
        "accounts:\n"
        "  personal-16bitdo:\n"
        "    github_login: 16BitDo\n"
        "    gh_config_dir: ~/.config/gh-16bitdo\n",
    )
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "16bitdo")
    results = AccountIdentityActualCheck().run(CheckContext())
    assert len(results) == 1
    assert results[0].severity is Severity.INFO


def test_all_digit_login_is_verified_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`github_login: 12345` 는 YAML 이 int 로 파싱한다.

    예전에는 비-문자열이라 조용히 skip 돼 **그 계정만 미검증**이 됐다. 이제는
    문자열로 되돌려 정상 검증한다 — 불일치면 CRITICAL 이 나와야 한다.
    """
    _wire(
        tmp_path,
        monkeypatch,
        "version: 1\n"
        "machine: test-machine\n"
        "accounts:\n"
        "  personal-16bitdo:\n"
        "    github_login: 12345\n"
        "    gh_config_dir: ~/.config/gh-16bitdo\n",
    )
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "heisgone")
    results = AccountIdentityActualCheck().run(CheckContext())
    assert len(results) == 1
    assert results[0].severity is Severity.CRITICAL


def test_unusable_login_value_is_still_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`github_login: yes` -> bool. 신원으로 쓸 수 없으므로 조용히 건너뛴다."""
    _wire(
        tmp_path,
        monkeypatch,
        "version: 1\n"
        "machine: test-machine\n"
        "accounts:\n"
        "  personal-16bitdo:\n"
        "    github_login: yes\n"
        "    gh_config_dir: ~/.config/gh-16bitdo\n",
    )
    monkeypatch.setattr(identity_probe, "gh_login", lambda d: "16bitdo")
    assert AccountIdentityActualCheck().run(CheckContext()) == []
