"""anvyc tools configure 통합 테스트 (PR3 — 번호 토글 폴백 경로).

ADAPTERS 순서: shell(1) git(2) aws(3) gh(4) cursor(5) claude(6) iterm2(7)
pulumi(8) dev_env(9) shell_prompt(10).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import yaml

from tests.integration._helpers import run_anvyc as _anvyc


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body))


def test_configure_toggle_and_write(tmp_path: Path) -> None:
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    _write(cfg, "version: 1\ntools: {}\n")
    # #3 = aws → off, confirm yes
    proc = _anvyc(
        "tools", "configure", "--config", str(cfg), cwd=tmp_path, input_str="3\ny\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert "wrote" in proc.stdout
    data = yaml.safe_load(cfg.read_text())
    assert data["tools"]["aws"]["enabled"] is False
    assert (cfg.parent / "anvyc.yaml.bak").is_file()


def test_configure_noop_when_empty(tmp_path: Path) -> None:
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    _write(cfg, "version: 1\ntools: {}\n")
    before = cfg.read_text()
    proc = _anvyc(
        "tools", "configure", "--config", str(cfg), cwd=tmp_path, input_str="\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert "변경 없음" in proc.stdout
    assert cfg.read_text() == before
    assert not (cfg.parent / "anvyc.yaml.bak").exists()


def test_configure_yes_skips_confirm(tmp_path: Path) -> None:
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    _write(cfg, "version: 1\ntools: {}\n")
    # #2 = git → off; --yes 라 확인 프롬프트 없음 (토글 입력만)
    proc = _anvyc(
        "tools", "configure", "--config", str(cfg), "--yes",
        cwd=tmp_path, input_str="2\n",
    )
    assert proc.returncode == 0, proc.stderr
    data = yaml.safe_load(cfg.read_text())
    assert data["tools"]["git"]["enabled"] is False


def test_configure_abort_does_not_write(tmp_path: Path) -> None:
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    _write(cfg, "version: 1\ntools: {}\n")
    before = cfg.read_text()
    proc = _anvyc(
        "tools", "configure", "--config", str(cfg), cwd=tmp_path, input_str="3\nn\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert "aborted" in proc.stdout
    assert cfg.read_text() == before
    assert not (cfg.parent / "anvyc.yaml.bak").exists()


def test_configure_missing_config_errors(tmp_path: Path) -> None:
    missing = tmp_path / ".anvyc" / "anvyc.yaml"
    proc = _anvyc(
        "tools", "configure", "--config", str(missing), cwd=tmp_path, input_str="\n"
    )
    assert proc.returncode == 1
    assert "부재" in (proc.stdout + proc.stderr)


def test_configure_preserves_other_tool_keys(tmp_path: Path) -> None:
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    _write(
        cfg,
        """\
        version: 1
        tools:
          shell:
            enabled: true
            files:
              - "~/.zshrc"
              - "~/.zprofile"
        """,
    )
    # #1 = shell → off; files 보존되어야
    proc = _anvyc(
        "tools", "configure", "--config", str(cfg), "--yes",
        cwd=tmp_path, input_str="1\n",
    )
    assert proc.returncode == 0, proc.stderr
    data = yaml.safe_load(cfg.read_text())
    assert data["tools"]["shell"]["enabled"] is False
    assert data["tools"]["shell"]["files"] == ["~/.zshrc", "~/.zprofile"]
