"""`anvyc … help` 전역 help 단어 별칭 검증 (HelpAliasGroup).

그룹 경로 끝의 `help` 토큰이 `--help` 와 동일하게 동작하는지, 미존재 명령
에러는 보존되는지, 리프 명령은 비대상(인자로 소비)인지 확인한다.

환경 견고성: `test_cli_help_panels.py` 와 동일하게 COLUMNS 고정 + ANSI 제거로
색/폭과 무관하게 본문만 검증한다.
"""

from __future__ import annotations

import re

from typer.testing import CliRunner

from anvyc.cli import app

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _run(args: list[str]) -> tuple[int, str]:
    """app 실행 — (exit_code, ANSI 제거·넓은폭 정규화 output)."""
    result = CliRunner().invoke(app, args, env={"COLUMNS": "200"})
    return result.exit_code, _ANSI_RE.sub("", result.output)


def test_root_help_word() -> None:
    """`anvyc help` → 루트 도움말, exit 0, top-level 그룹(aws) 노출."""
    code, out = _run(["help"])
    assert code == 0
    assert "Usage:" in out
    assert "aws" in out


def test_group_help_word() -> None:
    """`anvyc aws help` → aws 그룹 도움말, profile 서브그룹 노출."""
    code, out = _run(["aws", "help"])
    assert code == 0
    assert "Usage:" in out
    assert "profile" in out


def test_nested_group_help_word() -> None:
    """`anvyc aws profile help` → profile 도움말, 5개 서브커맨드 노출."""
    code, out = _run(["aws", "profile", "help"])
    assert code == 0
    assert "Usage:" in out
    for sub in ("list", "show", "create", "edit", "rm"):
        assert sub in out, f"서브커맨드 '{sub}' 누락"


def test_help_word_equivalent_to_flag() -> None:
    """`… profile help` 본문이 `… profile --help` 와 동등(정규화 후)."""
    code_word, out_word = _run(["aws", "profile", "help"])
    code_flag, out_flag = _run(["aws", "profile", "--help"])
    assert code_word == 0
    assert code_flag == 0
    assert out_word.strip() == out_flag.strip()


def test_unknown_command_still_errors() -> None:
    """회귀 가드: 미존재 명령은 기존 'No such command' 에러(exit 2) 유지."""
    code, out = _run(["aws", "bogus"])
    assert code == 2
    assert "No such command" in out


def test_leaf_command_help_is_argument_not_alias() -> None:
    """리프 경계: `… profile show help` 는 별칭 비발동 — help 가 show 의 인자.

    show 는 그룹이 아니라 Command 이므로 HelpAliasGroup 비대상이다. profile
    그룹 도움말(COMMAND 목록 헤더)이 출력되지 않아야 한다.
    """
    code, out = _run(["aws", "profile", "show", "help"])
    assert code != 0
    assert "Usage: anvyc aws profile [OPTIONS] COMMAND" not in out


def test_help_word_inert_during_completion() -> None:
    """shell completion(resilient_parsing) 중에는 help 별칭이 발동하지 않는다.

    완성 후보 스트림에 도움말 텍스트가 섞이는 회귀 방지 — echo/exit 금지.
    """
    import typer
    import typer._click as click

    root = typer.main.get_command(app)
    ctx = click.Context(root, info_name="anvyc", resilient_parsing=True)
    # 미존재 'help' 토큰: 정상 모드면 echo+exit 하지만 completion 모드면 None 반환.
    assert root.get_command(ctx, "help") is None
