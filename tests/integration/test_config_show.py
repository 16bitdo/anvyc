"""anvyc config show 통합 테스트."""
from __future__ import annotations

import textwrap
from pathlib import Path

import yaml

from tests.integration._helpers import run_anvyc as _anvyc


def test_config_show_raw_preserves_comments(tmp_path: Path) -> None:
    """default (raw) — 사용자가 작성한 코멘트가 출력에 그대로 보존."""
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    cfg.parent.mkdir()
    cfg.write_text(
        textwrap.dedent("""\
        # user comment 1
        version: 1
        storage:
          root: ".anvyc"  # inline
        tools:
          shell:
            enabled: true
        """)
    )

    proc = _anvyc("config", "show", "--config", str(cfg), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "user comment 1" in proc.stdout
    assert "# inline" in proc.stdout
    assert "version: 1" in proc.stdout


def test_config_show_effective_includes_defaults(tmp_path: Path) -> None:
    """--effective — yaml 에 명시 안 한 default (security.secret_scan 등) 도 포함."""
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    cfg.parent.mkdir()
    # security 미명시 — default 값으로 dump 되어야 함
    cfg.write_text(
        textwrap.dedent("""\
        version: 1
        tools:
          shell:
            enabled: true
        """)
    )

    proc = _anvyc(
        "config", "show", "--effective", "--config", str(cfg), cwd=tmp_path
    )
    assert proc.returncode == 0, proc.stderr
    # yaml 로 다시 parse 해서 default 들이 채워졌는지 확인
    parsed = yaml.safe_load(proc.stdout)
    assert "security" in parsed
    assert parsed["security"]["secret_scan"] is True
    assert parsed["security"]["block_on_secret"] is True
    assert "storage" in parsed
    assert parsed["storage"]["keep_backups"] == 5
    # internal field 인 source 는 노출 안 됨
    assert "source" not in parsed
