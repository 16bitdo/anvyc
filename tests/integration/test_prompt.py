"""anvyc prompt 통합 테스트 (v0.13.0 — shell prompt 세그먼트 명령)."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from tests.integration._helpers import run_anvyc as _anvyc


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body))


def test_prompt_routing_fields(tmp_path: Path) -> None:
    """.envrc + Pulumi.yaml → aws/claude/pulumi 세그먼트를 공백 구분 출력."""
    proj = tmp_path / "proj"
    cfg = tmp_path / ".claude-edward"
    cfg.mkdir()
    _write(
        proj / ".envrc",
        f'export AWS_PROFILE=company-dev\nexport CLAUDE_CONFIG_DIR="{cfg}"\n',
    )
    _write(
        proj / "Pulumi.yaml",
        "name: p\nruntime: python\nbackend:\n  url: s3://state\n",
    )

    proc = _anvyc("prompt", "--path", str(proj))
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    assert "aws:company-dev" in out
    assert "claude:edward" in out
    assert "pulumi:s3://state" in out


def test_prompt_json(tmp_path: Path) -> None:
    """--json → key→value 객체."""
    proj = tmp_path / "p"
    _write(proj / ".envrc", "export AWS_PROFILE=x\n")

    proc = _anvyc("prompt", "--path", str(proj), "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"aws": "x"}


def test_prompt_empty_dir_yields_blank(tmp_path: Path) -> None:
    """라우팅 신호 없는 디렉터리 → 빈 출력 (세그먼트 미표시)."""
    proj = tmp_path / "bare"
    proj.mkdir()

    proc = _anvyc("prompt", "--path", str(proj))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_prompt_empty_dir_json_is_empty_object(tmp_path: Path) -> None:
    """라우팅 신호 없음 + --json → 빈 객체."""
    proj = tmp_path / "bare2"
    proj.mkdir()

    proc = _anvyc("prompt", "--path", str(proj), "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {}


def test_prompt_missing_path_silent(tmp_path: Path) -> None:
    """존재하지 않는 경로 → 조용히 빈 출력 + exit 0 (셸 prompt 를 깨지 않음)."""
    proc = _anvyc("prompt", "--path", str(tmp_path / "nonexistent"))
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
