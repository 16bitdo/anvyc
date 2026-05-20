"""anvyc project doctor 통합 테스트 (P7, v0.8.1)."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from tests.integration._helpers import run_anvyc as _anvyc


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body))


@pytest.fixture
def patched_aws_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """~/.aws/config 를 tmp 로 isolate (project_doctor 의 aws check 용)."""
    cfg = tmp_path / "aws" / "config"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("[default]\nregion = ap-northeast-2\n[profile ws-dev]\n")
    monkeypatch.setenv("ANVYC_TEST_AWS_CONFIG", str(cfg))
    # aws_config 모듈은 환경 변수를 직접 보진 않으므로 monkeypatch 어렵다.
    # 실제 ~/.aws/config 를 그대로 사용하되, 검증 case 의 profile 명을
    # 사용자 실 profile 과 무관하게 잡는다 (test_unknown_aws_warns).
    return cfg


def test_all_ok_full_project(tmp_path: Path) -> None:
    """완전한 project — .envrc + .git + Pulumi.yaml + .python-version."""
    proj = tmp_path / "p"
    _write(
        proj / ".envrc",
        "export AWS_PROFILE=__definitely_not_a_real_profile_xyz__\n"
        "export NODE_ENV=development\n",
    )
    _write(
        proj / ".git" / "config",
        '[remote "origin"]\n    url = git@github.com:o/r.git\n',
    )
    _write(proj / "Pulumi.yaml", "name: p\nruntime: python\n")
    _write(proj / "Pulumi.dev.yaml", "config: {}\n")
    _write(proj / ".python-version", "3.13\n")

    proc = _anvyc("project", "doctor", "--path", str(proj), "--json")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    data = json.loads(proc.stdout)
    names = {r["check_name"] for r in data["results"]}
    # 적용 가능한 check 실행 (origin 은 plain github.com 이라 gh_account_routing 은 silent)
    assert {
        "aws_profile_defined",
        "github_remote_parseable",
        "pulumi_stacks_valid",
        "dev_env_secret_safety",
        "tool_versions_installed",
    } <= names


def test_dev_env_raw_secret_critical(tmp_path: Path) -> None:
    """`.envrc` 에 raw github token → dev_env_secret_safety CRITICAL."""
    proj = tmp_path / "leaky"
    _write(
        proj / ".envrc",
        "export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
    )

    proc = _anvyc("project", "doctor", "--path", str(proj), "--json")
    data = json.loads(proc.stdout)
    crit = [r for r in data["results"] if r["check_name"] == "dev_env_secret_safety"]
    assert len(crit) == 1
    assert crit[0]["severity"] == "critical"
    assert "GITHUB_TOKEN" in crit[0]["message"]


def test_dev_env_op_reference_safe(tmp_path: Path) -> None:
    """op:// reference 사용 → dev_env_secret_safety INFO."""
    proj = tmp_path / "safe"
    _write(
        proj / ".envrc",
        "export GITHUB_TOKEN=op://Personal/GitHub/token\n",
    )

    proc = _anvyc("project", "doctor", "--path", str(proj), "--json")
    data = json.loads(proc.stdout)
    sec = [r for r in data["results"] if r["check_name"] == "dev_env_secret_safety"]
    assert sec[0]["severity"] == "info"


def test_gh_account_routing_ok(tmp_path: Path) -> None:
    """origin ssh alias == .envrc GH_CONFIG_DIR gh 계정 → gh_account_routing INFO."""
    proj = tmp_path / "gh-ok"
    _write(
        proj / ".git" / "config",
        '[remote "origin"]\n    url = git@github.com-16bitdo:16bitdo/gh-ok.git\n',
    )
    _write(proj / ".envrc", 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n')

    proc = _anvyc("project", "doctor", "--path", str(proj), "--json")
    data = json.loads(proc.stdout)
    gh = [r for r in data["results"] if r["check_name"] == "gh_account_routing"]
    assert len(gh) == 1
    assert gh[0]["severity"] == "info"


def test_gh_account_routing_missing(tmp_path: Path) -> None:
    """ssh alias origin 인데 GH_CONFIG_DIR 없음 → gh_account_routing WARNING."""
    proj = tmp_path / "gh-missing"
    _write(
        proj / ".git" / "config",
        '[remote "origin"]\n    url = git@github.com-heisgone:whatap/gh-missing.git\n',
    )

    proc = _anvyc("project", "doctor", "--path", str(proj), "--json")
    data = json.loads(proc.stdout)
    gh = [r for r in data["results"] if r["check_name"] == "gh_account_routing"]
    assert len(gh) == 1
    assert gh[0]["severity"] == "warning"
    assert "GH_CONFIG_DIR" in gh[0]["message"]


def test_gh_account_routing_mismatch(tmp_path: Path) -> None:
    """gh 계정 ≠ origin ssh alias → gh_account_routing WARNING."""
    proj = tmp_path / "gh-mismatch"
    _write(
        proj / ".git" / "config",
        '[remote "origin"]\n    url = git@github.com-16bitdo:16bitdo/gh-mismatch.git\n',
    )
    _write(proj / ".envrc", 'export GH_CONFIG_DIR="$HOME/.config/gh-heisgone"\n')

    proc = _anvyc("project", "doctor", "--path", str(proj), "--json")
    data = json.loads(proc.stdout)
    gh = [r for r in data["results"] if r["check_name"] == "gh_account_routing"]
    assert len(gh) == 1
    assert gh[0]["severity"] == "warning"
    assert "불일치" in gh[0]["message"]


def test_gh_account_routing_silent_for_plain_origin(tmp_path: Path) -> None:
    """plain github.com origin (ssh alias 없음) → gh_account_routing 결과 0건."""
    proj = tmp_path / "gh-plain"
    _write(
        proj / ".git" / "config",
        '[remote "origin"]\n    url = git@github.com:o/r.git\n',
    )

    proc = _anvyc("project", "doctor", "--path", str(proj), "--json")
    data = json.loads(proc.stdout)
    gh = [r for r in data["results"] if r["check_name"] == "gh_account_routing"]
    assert gh == []


def test_pulumi_invalid_stack_name(tmp_path: Path) -> None:
    """stack 이름에 공백 → pulumi_stacks_valid WARNING."""
    proj = tmp_path / "p"
    _write(proj / "Pulumi.yaml", "name: p\nruntime: python\n")
    # 공백 + 특수문자 포함된 stack 이름
    _write(proj / "Pulumi.bad stack.yaml", "config: {}\n")

    proc = _anvyc("project", "doctor", "--path", str(proj), "--json")
    data = json.loads(proc.stdout)
    pul = [r for r in data["results"] if r["check_name"] == "pulumi_stacks_valid"]
    assert pul[0]["severity"] == "warning"


def test_strict_mode_exits_1_on_warning(tmp_path: Path) -> None:
    """--strict 시 warning 이상 → exit 1."""
    proj = tmp_path / "p"
    _write(proj / "Pulumi.yaml", "name: p\nruntime: python\n")
    _write(proj / "Pulumi.bad stack.yaml", "config: {}\n")

    proc = _anvyc("project", "doctor", "--path", str(proj), "--strict")
    assert proc.returncode == 1


def test_bare_path_yields_minimal_results(tmp_path: Path) -> None:
    """아무 marker 없음 → 모든 check skip (0 결과)."""
    proj = tmp_path / "bare"
    proj.mkdir()

    proc = _anvyc("project", "doctor", "--path", str(proj), "--json")
    data = json.loads(proc.stdout)
    assert data["results"] == []


def test_missing_path_exits_1(tmp_path: Path) -> None:
    proc = _anvyc("project", "doctor", "--path", str(tmp_path / "x"))
    assert proc.returncode == 1
    assert "path not found" in proc.stdout


def test_human_rendering(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    _write(proj / ".git" / "config", '[remote "origin"]\n    url = git@github.com:o/r.git\n')

    proc = _anvyc("project", "doctor", "--path", str(proj))
    assert proc.returncode == 0, proc.stderr
    assert "project doctor" in proc.stdout
    assert "github_remote_parseable" in proc.stdout
