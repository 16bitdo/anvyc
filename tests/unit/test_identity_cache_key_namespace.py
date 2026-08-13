"""gh 실체 조회 캐시 키의 네임스페이스 — 프로젝트별 check 와 전역 check 의 통일.

같은 gh 프로필을 조회하면서 캐시 키를 서로 다르게 만들면(프로젝트별 `.envrc` 라벨,
전역 논리 계정 ID) 값이 같아도 키가 갈려 **같은 프로필을 두 번 조회**한다. 훅이 Bash
명령마다 `project doctor` 를 호출하는 경로라 이 중복은 그대로 지연이 된다.

키는 "무엇과 비교하는가" 가 아니라 **"무엇을 조회했는가"**(= 조회한 config 디렉터리)
에서 파생돼야 한다. C1 으로 비교 대상이 manifest ownership 으로 바뀌었으므로 이
구분이 특히 중요하다 — 키가 비교 대상을 따라가면 서로 다른 프로필의 조회 결과가 한
키를 공유하는, 중복 조회보다 훨씬 나쁜 버그가 된다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.checks.account_identity import AccountIdentityActualCheck
from anvyc.checks.base import CheckContext
from anvyc.core import account_manifest, identity_probe, project_doctor

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


def _wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, envrc_account: str
) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_CACHE_DIR", str(tmp_path / "cache"))
    m = tmp_path / "account-routing.yaml"
    m.write_text(_PROJECTS, encoding="utf-8")
    b = tmp_path / "binds"
    b.mkdir()
    (b / "bindings.test-machine.yaml").write_text(_BINDINGS, encoding="utf-8")
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(m))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(b))
    monkeypatch.setattr(account_manifest, "machine_name", lambda: "test-machine")
    monkeypatch.setattr(identity_probe, "commit_email", lambda p: "16bitdo@gmail.com")

    for account in ("16bitdo", "heisgone"):
        d = tmp_path / "home" / ".config" / f"gh-{account}"
        d.mkdir(parents=True)
        (d / "hosts.yml").write_text("users: {}\n", encoding="utf-8")

    proj = tmp_path / "analysis"
    (proj / ".git").mkdir(parents=True)
    (proj / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:16bitdo/analysis.git\n', encoding="utf-8"
    )
    (proj / ".envrc").write_text(
        f'export GH_CONFIG_DIR="$HOME/.config/gh-{envrc_account}"\n', encoding="utf-8"
    )
    return proj


def test_project_check_key_follows_probed_dir_not_comparison_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """조회 대상은 `gh-heisgone`, 비교 대상(ownership)은 `16bitdo` 인 상황.

    키가 비교 대상(ownership `16bitdo`)에서 파생되면 heisgone 프로필의 조회 결과가
    16bitdo 키에 저장돼, 다른 프로젝트의 16bitdo 프로필 조회가 그 값을 그대로 읽는다.
    키는 반드시 **조회한 config 디렉터리**를 따라야 한다.
    """
    proj = _wire(tmp_path, monkeypatch, envrc_account="heisgone")
    captured: dict[str, object] = {}

    def spy_probe_cached(**kwargs: object) -> str | None:
        captured.update(kwargs)
        return "heisgone"

    monkeypatch.setattr(project_doctor.identity_cache, "probe_cached", spy_probe_cached)
    project_doctor.run_project_doctor(proj)

    probed_dir = tmp_path / "home" / ".config" / "gh-heisgone"
    assert captured.get("key") == f"gh:{probed_dir}", (
        f"캐시 키가 조회 대상({probed_dir})에서 파생되지 않음: {captured.get('key')!r}"
    )


def test_global_check_key_follows_probed_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """전역 check 도 논리 계정 ID 가 아니라 조회한 config 디렉터리로 키를 만든다."""
    _wire(tmp_path, monkeypatch, envrc_account="16bitdo")
    import anvyc.checks.account_identity as mod

    captured: dict[str, object] = {}

    def spy_probe_cached(**kwargs: object) -> str | None:
        captured.update(kwargs)
        return "16bitdo"

    monkeypatch.setattr(mod.identity_cache, "probe_cached", spy_probe_cached)
    AccountIdentityActualCheck().run(CheckContext())

    probed_dir = tmp_path / "home" / ".config" / "gh-16bitdo"
    assert captured.get("key") == f"gh:{probed_dir}", (
        f"전역 check 의 캐시 키가 논리 계정 ID 등 다른 것에서 파생됨: {captured.get('key')!r}"
    )


def test_project_and_global_checks_share_one_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 프로필을 보는 두 check 가 조회를 **한 번만** 한다 (M2 의 실제 증상).

    키가 갈려 있으면 `anvyc doctor` 와 `anvyc project doctor` 가 각각 `gh api user`
    를 호출한다 — 값도 같고 무효화 조건도 같은데 캐시가 안 먹는다.
    """
    proj = _wire(tmp_path, monkeypatch, envrc_account="16bitdo")
    calls: list[object] = []

    def counting_gh_login(config_dir: object) -> str:
        calls.append(config_dir)
        return "16bitdo"

    monkeypatch.setattr(identity_probe, "gh_login", counting_gh_login)

    project_doctor.run_project_doctor(proj)
    assert len(calls) == 1, f"project doctor 단독에서 {len(calls)}회 조회"

    AccountIdentityActualCheck().run(CheckContext())
    assert len(calls) == 1, (
        f"전역 check 가 같은 프로필을 다시 조회함 ({len(calls)}회) — 캐시 키가 갈려 있다"
    )


def test_different_profiles_do_not_share_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """서로 다른 프로필은 키를 공유하면 안 된다 — 통일의 반대 방향 회귀.

    "키를 하나로 합친다" 를 과하게 적용해 상수 키(`gh:current` 등)로 만들면 heisgone
    프로필의 조회 결과를 16bitdo 프로필 조회가 그대로 읽는다 — 이 게이트가 막으려는
    바로 그 사고를 캐시가 만들어낸다.
    """
    proj_a = _wire(tmp_path, monkeypatch, envrc_account="16bitdo")
    keys: list[object] = []

    def spy_probe_cached(**kwargs: object) -> str | None:
        keys.append(kwargs.get("key"))
        return "16bitdo"

    monkeypatch.setattr(project_doctor.identity_cache, "probe_cached", spy_probe_cached)
    project_doctor.run_project_doctor(proj_a)
    (proj_a / ".envrc").write_text(
        'export GH_CONFIG_DIR="$HOME/.config/gh-heisgone"\n', encoding="utf-8"
    )
    project_doctor.run_project_doctor(proj_a)

    assert len(keys) == 2
    assert keys[0] != keys[1], f"서로 다른 프로필이 같은 캐시 키를 씀: {keys[0]!r}"
