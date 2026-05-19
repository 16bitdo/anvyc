"""anvyc project show 통합 테스트 (P1, v0.8.0).

D11c: dev_env 의 secret 패턴 매칭 자동 ***REDACTED*** 검증.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path


def _anvyc(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [str(Path(sys.executable).parent / "anvyc"), *args]
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True
    )


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body))


def test_full_project_json(tmp_path: Path) -> None:
    """.envrc + .git + Pulumi.yaml + Pulumi.<stack>.yaml + .python-version → 모든 필드 채워짐."""
    proj = tmp_path / "proj"
    _write(proj / ".envrc", "export AWS_PROFILE=company-dev\nexport NODE_ENV=development\n")
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
