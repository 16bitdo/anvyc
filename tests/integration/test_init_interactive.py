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
    # cursor 추가 3 prompt (mask N, gsa "", projects N — 모두 default) +
    # 1 final write confirm. 안전 여유 → 25 Enter (남으면 무해).
    proc = _anvyc(
        "init", "--interactive",
        "--root", str(tmp_path),
        input_str=_enter_only(25),
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
        "",       # cursor mask_mcp_tokens (default N)
        "",       # cursor globalStorage allowlist (default empty)
        "",       # cursor projects.enabled (default N)
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


def test_wizard_cursor_advanced_options(tmp_path: Path) -> None:
    """cursor 의 mask_mcp_tokens / globalStorage_allowlist / projects.enabled 활성."""
    answers = [
        "n",                 # shell disable
        "n",                 # shell_prompt disable
        "n",                 # git disable
        "n",                 # aws disable
        "n",                 # gh disable
        "n",                 # pulumi disable
        "",                  # cursor enable Y
        "y",                 # cursor mask_mcp_tokens YES
        "anysphere.cursor-mcp, ms-python.python",  # cursor gsa csv
        "y",                 # cursor projects.enabled YES
        "~/dev, ~/workspace",  # cursor projects.roots csv
        "n",                 # claude disable
        "n",                 # iterm2 disable
        "n",                 # dev_env disable
        "",                  # final write confirm Y
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
    cursor = parsed["tools"]["cursor"]
    assert cursor["enabled"] is True
    assert cursor["global"]["mask_mcp_tokens"] is True
    assert cursor["ide"]["global_storage_allowlist"] == [
        "anysphere.cursor-mcp",
        "ms-python.python",
    ]
    assert cursor["projects"]["enabled"] is True
    assert cursor["projects"]["roots"] == ["~/dev", "~/workspace"]


def test_wizard_cursor_defaults_minimal(tmp_path: Path) -> None:
    """cursor enable + 모든 추가 prompt default → entry 에 minimal cursor schema 박힘."""
    answers = [
        "n", "n", "n", "n", "n", "n",   # 6 file-based 도구 disable
        "",                              # cursor enable Y
        "",                              # cursor mask default N
        "",                              # cursor gsa default empty
        "",                              # cursor projects default N
        "n", "n", "n",                   # claude / iterm2 / dev_env disable
        "",                              # final write Y
    ]
    proc = _anvyc(
        "init", "--interactive",
        "--root", str(tmp_path),
        input_str="\n".join(answers) + "\n",
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    cursor = yaml.safe_load((tmp_path / ".anvyc" / "anvyc.yaml").read_text())["tools"]["cursor"]
    assert cursor["enabled"] is True
    assert cursor["global"]["mask_mcp_tokens"] is False
    assert cursor["ide"]["global_storage_allowlist"] == []
    assert cursor["projects"]["enabled"] is False
    assert cursor["projects"]["roots"] == []


def test_wizard_mutual_exclusion_with_from_git(tmp_path: Path) -> None:
    """--interactive --from-git 동시 지정 → exit 1."""
    proc = _anvyc(
        "init", "--interactive", "--from-git", "file:///tmp/fake-repo",
        "--root", str(tmp_path),
        cwd=tmp_path,
    )
    assert proc.returncode == 1
    assert "동시 사용 불가" in proc.stdout or "동시 사용 불가" in proc.stderr


def test_wizard_prompts_show_enter_default_hint(tmp_path: Path) -> None:
    """모든 confirm prompt 가 'Enter=Yes' / 'Enter=No' 힌트로 default 를 명시한다.

    25 Enter 입력 시 cursor 도 enable 되므로 Layer A / Layer C 도 출력된다.
    기대 카운트:
      - Enter=Yes: 9 (shell/shell_prompt/git/aws/gh/pulumi/cursor/claude/iterm2) + 1 (Write) = 10
      - Enter=No:  1 (dev_env) + 2 (Layer A, Layer C) = 3
    """
    proc = _anvyc(
        "init", "--interactive",
        "--root", str(tmp_path),
        input_str=_enter_only(25),
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    out = proc.stdout
    assert out.count("(Enter=Yes)") == 10, (
        f"expected 10 Enter=Yes prompts, got {out.count('(Enter=Yes)')}\n--- stdout ---\n{out}"
    )
    assert out.count("(Enter=No)") == 3, (
        f"expected 3 Enter=No prompts, got {out.count('(Enter=No)')}\n--- stdout ---\n{out}"
    )
    # dev_env 만 Enter=No 인 확인 (회귀 가드)
    assert "Enable dev_env? (Enter=No)" in out
    assert "Enable shell? (Enter=Yes)" in out
    # Layer B text prompt — Korean hint 제거, (Enter=skip) 패턴 일관 적용
    assert "Layer B: globalStorage allowlist csv (Enter=skip)" in out
    assert "(빈 입력 = 없음)" not in out


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
