"""anvyc project list 통합 테스트 (P2, v0.8.1)."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from tests.integration._helpers import run_anvyc as _anvyc


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_list_json_schema(tmp_path: Path) -> None:
    """발견된 각 project entry 가 project show schema 와 동일."""
    docs = tmp_path / "docs"
    docs.mkdir()
    _write(docs / "proj-a" / ".git" / "config", "")
    _write(docs / "proj-b" / "Pulumi.yaml", "name: b\nruntime: python\n")

    proc = _anvyc("project", "list", "--root", str(docs), "--json")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    data = json.loads(proc.stdout)
    assert isinstance(data, list)
    assert len(data) == 2
    for entry in data:
        # project show schema 와 동일
        assert set(entry.keys()) >= {
            "path", "aws_profile", "gh_account", "github", "pulumi",
            "dev_env", "tool_versions",
        }


def test_list_empty_root(tmp_path: Path) -> None:
    """발견 0건 → 빈 array."""
    docs = tmp_path / "empty"
    docs.mkdir()
    proc = _anvyc("project", "list", "--root", str(docs), "--json")
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == []


def test_list_multi_root(tmp_path: Path) -> None:
    r1 = tmp_path / "r1"
    r2 = tmp_path / "r2"
    r1.mkdir()
    r2.mkdir()
    _write(r1 / "p1" / ".git" / "config", "")
    _write(r2 / "p2" / ".git" / "config", "")

    proc = _anvyc(
        "project", "list", "--root", str(r1), "--root", str(r2), "--json"
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert len(data) == 2


def test_list_redaction_default(tmp_path: Path) -> None:
    """D11c — 각 project 의 dev_env secret 도 redacted."""
    docs = tmp_path / "docs"
    docs.mkdir()
    proj = docs / "secret-proj"
    _write(proj / ".git" / "config", "")
    _write(proj / ".envrc", "export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n")

    proc = _anvyc("project", "list", "--root", str(docs), "--json")
    data = json.loads(proc.stdout)
    assert data[0]["dev_env"]["GITHUB_TOKEN"] == "***REDACTED***"


def test_list_human_rendering(tmp_path: Path) -> None:
    """--json 없이는 사람 가독 표 (간단 sanity)."""
    docs = tmp_path / "docs"
    docs.mkdir()
    _write(
        docs / "myproj" / ".git" / "config",
        textwrap.dedent("""\
        [remote "origin"]
            url = git@github.com:acme/myproj.git
        """),
    )

    proc = _anvyc("project", "list", "--root", str(docs))
    assert proc.returncode == 0, proc.stderr
    assert "1 project" in proc.stdout
    # acme 는 github column 으로 truncate 영향 적음; path column 은 Rich 가 자동 truncate.
    assert "acme" in proc.stdout
