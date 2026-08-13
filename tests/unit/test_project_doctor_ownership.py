"""ownership — manifest 선언과 실제 커밋 신원 대조."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.checks.base import Severity
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
    ssh_alias: github.com-16bitdo
    gh_config_dir: ~/.config/gh-16bitdo
"""


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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

    proj = tmp_path / "analysis"
    (proj / ".git").mkdir(parents=True)
    (proj / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:16bitdo/analysis.git\n', encoding="utf-8"
    )
    return proj


def _result(report, name):
    return next((r for r in report.results if r.check_name == name), None)


def test_expected_commit_email_from_manifest(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(identity_probe, "commit_email", lambda p: "16bitdo@gmail.com")
    report = project_doctor.run_project_doctor(repo)
    assert report.expected_commit_email == "16bitdo@gmail.com"
    assert report.to_payload()["expected_commit_email"] == "16bitdo@gmail.com"
    # 리뷰 I2 — 일치(INFO) 분기 자체가 이전엔 미검증이었다: Severity.INFO 를
    # Severity.WARNING 으로 바꿔도 이 테스트를 포함한 5개가 전부 GREEN 이었다.
    # WARNING 은 is_blocking=True 라 CLI "조치 필요" 섹션에 잘못 올라간다 —
    # 정상 상태인데 조치가 필요한 것처럼 보이는, 사용자에게 실제로 보이는 회귀다.
    res = _result(report, "commit_identity_actual")
    assert res is not None and res.severity is Severity.INFO


def test_commit_identity_mismatch_is_critical(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(identity_probe, "commit_email", lambda p: "jklee@whatap.io")
    report = project_doctor.run_project_doctor(repo)
    res = _result(report, "commit_identity_actual")
    assert res is not None and res.severity is Severity.CRITICAL
    assert "jklee@whatap.io" in res.message


def test_commit_identity_unresolved_is_warning(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """fail-closed 상태(useConfigOnly, 신원 없음) — 커밋이 아예 안 되는 상황."""
    monkeypatch.setattr(identity_probe, "commit_email", lambda p: None)
    report = project_doctor.run_project_doctor(repo)
    res = _result(report, "commit_identity_actual")
    assert res is not None and res.severity is Severity.WARNING
    assert "fail-closed" in res.message


def test_undeclared_repo_is_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANVYC_ACCOUNT_MANIFEST", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(tmp_path / "nope"))
    proj = tmp_path / "other"
    (proj / ".git").mkdir(parents=True)
    (proj / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:someone/other.git\n', encoding="utf-8"
    )
    report = project_doctor.run_project_doctor(proj)
    assert _result(report, "commit_identity_actual") is None
    assert "expected_commit_email" not in report.to_payload()


# ---------------------------------------------------------------------------
# 위 4개는 commit_email 을 인자 무관 고정값(lambda p: "값")으로 대체하는 mock 이라,
# "무엇이 실제로 commit_email 에 전달되는가"의 회귀는 못 잡는다 — Task 4 의 gh_login
# 회귀(전달 인자가 리터럴 "$HOME/..." 라 실제로는 probe 가 항상 실패하는데도 인자
# 무관 mock 아래서는 4/4 통과)와 같은 계열이다. 아래 1개는 spy 로 실제 전달값을
# 기록해, "path 인자 대신 실수로 다른 경로(예: 프로세스 cwd)를 참조" 하는 회귀를
# 직접 잡는다.
# ---------------------------------------------------------------------------


def test_commit_email_receives_repo_path_not_process_cwd(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """commit_email 에 전달되는 경로가 프로세스 cwd 가 아니라 실제 대상 저장소여야 한다.

    `anvyc project doctor` 는 CLI `--path`(임의 디렉터리에서 실행 가능)와 MCP
    `Path(args.get("path") or ".")` 양쪽에서 호출되므로, 프로세스의 실제 cwd 와
    검사 대상 저장소가 다른 것이 정상적인 사용 패턴이다. 이 check 가 `path` 인자
    대신 실수로 `Path.cwd()` 등 다른 경로를 참조해도, 인자를 무시하는 mock
    (`lambda p: "값"`) 아래서는 위 4개 테스트가 전부 그대로 통과한다 — mock 이
    "무엇이 호출됐나"만 보장하고 "어떤 인자로 호출됐나"는 가리기 때문이다.
    cwd 를 저장소 밖(부모 디렉터리)으로 옮겨 두고도 여전히 저장소 자신의 절대경로가
    전달되는지 spy 로 직접 확인한다.
    """
    monkeypatch.chdir(repo.parent)
    received: list[object] = []

    def spy_commit_email(p: object) -> str:
        received.append(p)
        return "16bitdo@gmail.com"

    monkeypatch.setattr(identity_probe, "commit_email", spy_commit_email)
    project_doctor.run_project_doctor(repo)

    assert len(received) == 1, f"commit_email 이 {len(received)}회 호출됨 (기대 1회)"
    passed = Path(str(received[0]))
    assert passed.resolve() == repo.resolve(), (
        f"commit_email 에 잘못된 경로 전달: {passed!r} (기대: {repo!r})"
    )


# ---------------------------------------------------------------------------
# 리뷰 I1 — manifest 우선 로직(`if resolved.github_login: report.expected_gh_user =
# resolved.github_login`)이 무방비였다: 그 대입문을 통째로 지워도 기존 9개 테스트
# (본 파일 5개 + test_project_doctor_expected.py 4개) + 전체 unit 스위트 1194개가
# 전부 GREEN 이었다. 브리프가 명시한 핵심 설계 결정("manifest ownership 이 .envrc
# 라벨보다 우선한다 — L1 이 SoT")에 회귀 테스트가 하나도 없었다는 뜻이다. `.envrc`
# 와 manifest 가 서로 다른 gh 계정을 선언하는 충돌을 직접 구성해 검증한다.
# ---------------------------------------------------------------------------


def test_manifest_gh_user_overrides_envrc_label(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """manifest ownership 선언이 있으면 `.envrc` GH_CONFIG_DIR 라벨보다 우선한다 (L1 이 SoT).

    `.envrc` 는 'someoneelse' 계정을 가리키고 manifest(바인딩)는 '16bitdo' 를
    선언하는 충돌 상황을 구성한다. `.envrc` 라벨만 봤다면 `expected_gh_user` 는
    'someoneelse' 여야 하지만, manifest 선언이 있으면 그쪽이 이겨야 한다.
    """
    (repo / ".envrc").write_text(
        'export GH_CONFIG_DIR="$HOME/.config/gh-someoneelse"\n', encoding="utf-8"
    )
    monkeypatch.setattr(identity_probe, "commit_email", lambda p: "16bitdo@gmail.com")
    report = project_doctor.run_project_doctor(repo)
    assert report.expected_gh_user == "16bitdo", (
        f"manifest 선언(16bitdo)이 .envrc 라벨(someoneelse)을 이겨야 하는데: "
        f"{report.expected_gh_user!r}"
    )
