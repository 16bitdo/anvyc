"""anvyc config show --effective --json 통합 테스트 (P5, v0.8.0)."""
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


def test_config_show_effective_json(tmp_path: Path) -> None:
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    cfg.parent.mkdir()
    cfg.write_text(
        textwrap.dedent("""\
        version: 1
        tools:
          shell:
            enabled: true
        """)
    )

    proc = _anvyc(
        "config", "show", "--effective", "--json", "--config", str(cfg),
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert isinstance(data, dict)
    # default 값까지 채워졌는지
    assert data["security"]["secret_scan"] is True
    assert data["storage"]["keep_backups"] == 5
    # internal fields 노출 안 됨
    assert "source" not in data
    assert "overlay_source" not in data


def test_config_show_raw_no_json(tmp_path: Path) -> None:
    """--json 없이는 raw yaml 그대로 (사용자 코멘트 보존)."""
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    cfg.parent.mkdir()
    cfg.write_text("# my comment\nversion: 1\ntools: {}\n")

    proc = _anvyc("config", "show", "--config", str(cfg), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "# my comment" in proc.stdout
