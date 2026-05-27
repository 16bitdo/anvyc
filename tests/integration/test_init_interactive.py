"""anvyc init --interactive 통합 테스트.

stdin 으로 10 도구 prompt + 마지막 confirm 에 답한다 (v0.16.0+: shell_prompt 추가).
typer 의 default 처리:
- confirm: Y/N (Enter → default Y)
- prompt: "" (Enter) → default 값
"""
from __future__ import annotations

from pathlib import Path

import yaml

from tests.integration._helpers import run_anvyc as _anvyc


def _enter_only(n: int) -> str:
    """n 줄의 Enter (default accept) 입력."""
    return "\n" * n


def test_wizard_all_default_writes_yaml(tmp_path: Path) -> None:
    """모든 도구 Y + file default 그대로 + 마지막 Y → yaml 작성."""
    # 10 enable confirm + 6 file prompt (shell/shell_prompt/git/aws/gh/pulumi) +
    # 2 dev_env prompt (roots, patterns) + 1 final write confirm = 19 Enter
    proc = _anvyc(
        "init", "--interactive",
        "--root", str(tmp_path),
        input_str=_enter_only(19),
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    assert cfg.is_file()
    parsed = yaml.safe_load(cfg.read_text())
    assert "tools" in parsed
    # 10 tools 모두 enabled (dev_env 만 default n) → 9 tools enabled
    enabled_tools = {n for n, c in parsed["tools"].items() if c.get("enabled")}
    assert "shell" in enabled_tools
    assert "shell_prompt" in enabled_tools  # PR C — v0.16.0 신규
    assert "git" in enabled_tools
    assert "aws" in enabled_tools
    assert "cursor" in enabled_tools
    # dev_env 은 default disabled — 첫 Enter (default n) 면 disabled
    assert parsed["tools"]["dev_env"]["enabled"] is False


def test_wizard_partial_disable(tmp_path: Path) -> None:
    """일부 도구 (git, iterm2) disable + 나머지 default + write."""
    # 입력 시퀀스 (v0.16.0+: shell_prompt 추가 — wizard 10 도구):
    # shell:        Enter (Y) → file prompt Enter
    # shell_prompt: Enter (Y) → file prompt Enter
    # git:          n
    # aws:          Enter (Y) → file prompt Enter
    # gh:           Enter (Y) → file prompt Enter
    # pulumi:       Enter (Y) → file prompt Enter
    # cursor:       Enter (Y)
    # claude:       Enter (Y)
    # iterm2:       n
    # dev_env:      Enter (default n)
    # write:        Enter (Y)
    answers = [
        "",       # shell enable Y (default)
        "",       # shell files
        "",       # shell_prompt enable Y
        "",       # shell_prompt files
        "n",      # git disable
        "",       # aws enable Y
        "",       # aws files
        "",       # gh enable Y
        "",       # gh files
        "",       # pulumi enable Y
        "",       # pulumi files
        "",       # cursor enable Y
        "",       # claude enable Y
        "n",      # iterm2 disable
        "",       # dev_env (default n)
        "",       # final write confirm Y
    ]
    input_str = "\n".join(answers) + "\n"

    proc = _anvyc(
        "init", "--interactive",
        "--root", str(tmp_path),
        input_str=input_str,
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    parsed = yaml.safe_load((tmp_path / ".anvyc" / "anvyc.yaml").read_text())
    tools = parsed["tools"]
    assert tools["git"]["enabled"] is False
    assert tools["iterm2"]["enabled"] is False
    assert tools["shell"]["enabled"] is True
    assert tools["aws"]["enabled"] is True


def test_wizard_mutual_exclusion_with_from_git(tmp_path: Path) -> None:
    """--interactive --from-git 동시 지정 → exit 1."""
    proc = _anvyc(
        "init", "--interactive", "--from-git", "file:///tmp/fake-repo",
        "--root", str(tmp_path),
        cwd=tmp_path,
    )
    assert proc.returncode == 1
    assert "동시 사용 불가" in proc.stdout or "동시 사용 불가" in proc.stderr


def test_wizard_existing_yaml_without_force_fails(tmp_path: Path) -> None:
    """기존 anvyc.yaml 존재 + --force 없음 → exit 1."""
    anvyc_dir = tmp_path / ".anvyc"
    anvyc_dir.mkdir()
    (anvyc_dir / "anvyc.yaml").write_text("version: 1\n")

    proc = _anvyc(
        "init", "--interactive",
        "--root", str(tmp_path),
        input_str="",
        cwd=tmp_path,
    )
    assert proc.returncode == 1
    assert "이미 존재" in proc.stdout
