"""anvyc project show 통합 테스트 (P1, v0.8.0).

D11c: dev_env 의 secret 패턴 매칭 자동 ***REDACTED*** 검증.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from tests.integration._helpers import run_anvyc as _anvyc


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body))


def test_full_project_json(tmp_path: Path) -> None:
    """.envrc + .git + Pulumi.yaml + Pulumi.<stack>.yaml + .python-version → 모든 필드 채워짐."""
    proj = tmp_path / "proj"
    _write(
        proj / ".envrc",
        "export AWS_PROFILE=company-dev\n"
        'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n'
        "export NODE_ENV=development\n",
    )
    _write(
        proj / ".git" / "config",
        """\
        [remote "origin"]
            url = git@github.com-16bitdo:16bitdo/proj.git
        """,
    )
    _write(proj / "Pulumi.yaml", "name: proj\nruntime: python\n")
    _write(proj / "Pulumi.dev.yaml", "config: {}\n")
    _write(proj / ".python-version", "3.13\n")

    proc = _anvyc("project", "show", "--path", str(proj), "--json")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    data = json.loads(proc.stdout)
    assert data["aws_profile"] == "company-dev"
    # GH_CONFIG_DIR 경로 값 → gh 계정 (basename 의 gh- prefix 제거)
    assert data["gh_account"] == "16bitdo"
    assert data["dev_env"]["NODE_ENV"] == "development"
    assert len(data["github"]) == 1
    assert data["github"][0]["owner"] == "16bitdo"
    assert data["github"][0]["ssh_alias"] == "16bitdo"
    assert data["pulumi"]["project_name"] == "proj"
    assert data["pulumi"]["stacks"] == ["dev"]
    assert data["tool_versions"]["python"] == "3.13"


def test_bare_project_all_null(tmp_path: Path) -> None:
    """아무 파일도 없음 → 대부분 null/empty."""
    proj = tmp_path / "bare"
    proj.mkdir()

    proc = _anvyc("project", "show", "--path", str(proj), "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["aws_profile"] is None
    assert data["gh_account"] is None
    assert data["claude_account"] is None
    assert data["github"] is None
    assert data["pulumi"] is None
    assert data["dev_env"] == {}
    assert data["tool_versions"] == {}


def test_secret_redaction_default(tmp_path: Path) -> None:
    """D11c — secret 패턴 매칭되는 dev_env 값은 ***REDACTED***."""
    proj = tmp_path / "secret"
    _write(
        proj / ".envrc",
        # AKIA prefix = aws_access_key pattern
        "export AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF\n"
        "export AWS_PROFILE=normal-profile\n"
        # github_token pattern
        "export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
    )

    proc = _anvyc("project", "show", "--path", str(proj), "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["dev_env"]["AWS_ACCESS_KEY_ID"] == "***REDACTED***"
    assert data["dev_env"]["GITHUB_TOKEN"] == "***REDACTED***"
    # 일반 값은 그대로
    assert data["dev_env"]["AWS_PROFILE"] == "normal-profile"
    # 편의 single-field 도 raw 그대로 (KEY 자체는 secret 아님)
    assert data["aws_profile"] == "normal-profile"


def test_reveal_secrets_flag(tmp_path: Path) -> None:
    """--reveal-secrets 지정 시 raw 값 노출."""
    proj = tmp_path / "reveal"
    _write(proj / ".envrc", "export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n")

    proc = _anvyc(
        "project", "show", "--path", str(proj), "--json", "--reveal-secrets"
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["dev_env"]["GITHUB_TOKEN"].startswith("ghp_")
    assert "REDACTED" not in data["dev_env"]["GITHUB_TOKEN"]


def test_op_reference_not_redacted(tmp_path: Path) -> None:
    """op:// 1Password reference 는 placeholder → redaction 면제."""
    proj = tmp_path / "op"
    _write(
        proj / ".envrc",
        "export GITHUB_TOKEN=op://Personal/GitHub/token\n",
    )

    proc = _anvyc("project", "show", "--path", str(proj), "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["dev_env"]["GITHUB_TOKEN"] == "op://Personal/GitHub/token"


def test_gh_account_non_convention_dir_is_null(tmp_path: Path) -> None:
    """GH_CONFIG_DIR basename 이 `gh-<name>` 형식이 아니면 gh_account 는 null."""
    proj = tmp_path / "ghx"
    _write(proj / ".envrc", 'export GH_CONFIG_DIR="$HOME/.config/gh"\n')

    proc = _anvyc("project", "show", "--path", str(proj), "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["gh_account"] is None
    # 경로 값 자체는 dev_env 에 그대로 남음 (secret 아님)
    assert data["dev_env"]["GH_CONFIG_DIR"] == "$HOME/.config/gh"


def test_claude_account_derived(tmp_path: Path) -> None:
    """`.envrc` 의 CLAUDE_CONFIG_DIR 경로 → claude_account 도출 (basename .claude- strip)."""
    proj = tmp_path / "claude"
    _write(proj / ".envrc", 'export CLAUDE_CONFIG_DIR="$HOME/.claude-edward"\n')

    proc = _anvyc("project", "show", "--path", str(proj), "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["claude_account"] == "edward"
    # 경로 값 자체는 dev_env 에 그대로 남음 (secret 아님)
    assert data["dev_env"]["CLAUDE_CONFIG_DIR"] == "$HOME/.claude-edward"


def test_claude_account_default_dir_is_null(tmp_path: Path) -> None:
    """suffix 없는 기본 `~/.claude` → claude_account 는 null."""
    proj = tmp_path / "claude-default"
    _write(proj / ".envrc", 'export CLAUDE_CONFIG_DIR="$HOME/.claude"\n')

    proc = _anvyc("project", "show", "--path", str(proj), "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["claude_account"] is None


def test_missing_path_fails(tmp_path: Path) -> None:
    proc = _anvyc("project", "show", "--path", str(tmp_path / "nonexistent"))
    assert proc.returncode == 1
    assert "path not found" in proc.stdout


def test_human_rendering(tmp_path: Path) -> None:
    """--json 없으면 사람-가독 형식 (간단 sanity)."""
    proj = tmp_path / "h"
    _write(proj / ".envrc", "export AWS_PROFILE=x\n")

    proc = _anvyc("project", "show", "--path", str(proj))
    assert proc.returncode == 0, proc.stderr
    assert "aws_profile" in proc.stdout
    assert "x" in proc.stdout
