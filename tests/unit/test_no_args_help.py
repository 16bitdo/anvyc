"""no-args 그룹 호출 시 도움말 일관화 검증 (#175 help 단어 별칭의 후속·별건).

루트 `anvyc` 는 인자 없이 호출하면 도움말을 출력하지만(`no_args_is_help`),
서브그룹(`anvyc aws`, `anvyc config` …)은 루트와 달리 `Missing command`
에러(exit 2)를 냈다. 모든 Typer 그룹이 루트와 동일하게 인자 없이 호출 시
도움말을 출력하도록 일관화한 동작을 검증한다.

환경 견고성: `test_help_alias.py` 와 동일하게 COLUMNS 고정 + ANSI 제거로
색/폭과 무관하게 본문만 검증한다.
"""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from anvyc.cli import app

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# (그룹 경로, 도움말에 반드시 나타나야 할 자식 명령/서브그룹 토큰)
# 모든 top-level 그룹 + 모든 중첩 그룹을 망라한다.
_GROUPS: list[tuple[list[str], str]] = [
    (["git"], "init"),
    (["sops"], "encrypt"),
    (["config"], "roots"),
    (["config", "roots"], "clear"),
    (["config", "projects"], "exclude"),
    (["tools"], "configure"),
    (["project"], "doctor"),
    (["aws"], "profile"),
    (["aws", "profile"], "create"),
    (["snapshot"], "create"),
    (["creds"], "rotate"),
    (["sync"], "push"),
    (["sync", "conflict"], "resolve"),
    (["workctx"], "switch"),
    (["cost"], "summary"),
    (["runs"], "summary"),
    (["secret"], "get"),
    (["mcp"], "install"),
    (["guard"], "protect"),
]


def _run(args: list[str]) -> tuple[int, str]:
    """app 실행 — (exit_code, ANSI 제거·넓은폭 정규화 output)."""
    result = CliRunner().invoke(app, args, env={"COLUMNS": "200"})
    return result.exit_code, _ANSI_RE.sub("", result.output)


@pytest.mark.parametrize(
    ("path", "child"), _GROUPS, ids=lambda v: v if isinstance(v, str) else " ".join(v)
)
def test_group_no_args_shows_help(path: list[str], child: str) -> None:
    """그룹을 인자 없이 호출하면 `Missing command` 에러 대신 도움말을 출력한다."""
    code, out = _run(path)
    assert "Usage:" in out, f"{' '.join(path)} no-args 에 Usage 누락:\n{out}"
    assert child in out, f"{' '.join(path)} no-args 도움말에 자식 '{child}' 누락:\n{out}"
    assert "Missing command" not in out, f"{' '.join(path)} no-args 가 여전히 에러:\n{out}"


def test_no_args_equivalent_to_help_flag() -> None:
    """대표 그룹의 no-args 도움말 본문이 `--help` 본문과 동등(정규화 후)."""
    for path in (["aws"], ["config"], ["sync"], ["aws", "profile"]):
        _, out_bare = _run(path)
        _, out_flag = _run([*path, "--help"])
        assert out_bare.strip() == out_flag.strip(), f"{' '.join(path)} no-args != --help"


def test_all_groups_no_args_consistent_with_root() -> None:
    """모든 그룹의 no-args exit code 가 루트(`anvyc`)와 동일(일관)하다."""
    root_code, root_out = _run([])
    assert "Usage:" in root_out  # 루트는 인자 없이 도움말 출력 (일관화 기준)
    for path, _child in _GROUPS:
        code, _ = _run(path)
        assert code == root_code, f"{' '.join(path)} exit={code} != root {root_code}"
