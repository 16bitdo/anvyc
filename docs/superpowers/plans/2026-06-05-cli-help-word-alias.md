# 전역 `help` 단어 별칭 (anvyc … help) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** anvyc CLI의 모든 그룹 레벨에서 경로 끝의 `help` 단어를 `--help`와 동일하게 동작시킨다 (`anvyc help`, `anvyc aws help`, `anvyc aws profile help`).

**Architecture:** `TyperGroup`를 상속한 `HelpAliasGroup` 단일 클래스가 `get_command`에서 미존재 `help` 토큰을 가로채 `ctx.get_help()`를 출력하고 exit한다. 얇은 팩토리 `_typer()`가 이 클래스를 모든 Typer 앱의 기본 그룹 클래스로 강제해, `cli.py`의 20개 `typer.Typer()` 호출을 한 번에 통일한다.

**Tech Stack:** Python 3, Typer 0.26.2, Click 8.4.1, pytest (`typer.testing.CliRunner`), ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-06-05-cli-help-word-alias-design.md`

---

## File Structure

- **Modify** `src/anvyc/cli.py`:
  - imports: `import click`, `from typer.core import TyperGroup` 추가 (현재 둘 다 없음)
  - imports 직후 / 루트 `app` 정의(현 line 100) 직전에 `HelpAliasGroup` 클래스 + `_typer()` 팩토리 추가
  - 기존 20개 `typer.Typer(` 호출 사이트 → `_typer(` 로 교체 (팩토리 내부 `typer.Typer(**kwargs)` 1개는 보존)
- **Create** `tests/unit/test_help_alias.py`: 별칭 동등성 + 회귀 가드 + 리프 경계 검증

---

## Task 1: `HelpAliasGroup` + `_typer()` 팩토리 — 전역 help 단어 별칭 (TDD)

**Files:**
- Create: `tests/unit/test_help_alias.py`
- Modify: `src/anvyc/cli.py` (imports; 신규 class/factory; 20개 `typer.Typer(`→`_typer(` 호출 사이트)

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_help_alias.py` 를 아래 내용으로 생성:

```python
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/unit/test_help_alias.py -v`
Expected: `test_root_help_word`, `test_group_help_word`, `test_nested_group_help_word`, `test_help_word_equivalent_to_flag` 4개 **FAIL** (현재 `help` → exit 2 "No such command"). `test_unknown_command_still_errors`, `test_leaf_command_help_is_argument_not_alias` 2개는 PASS (구현 전부터 성립하는 경계/회귀 가드).

- [ ] **Step 3: import 추가**

`src/anvyc/cli.py` line 16 `import typer` 를 아래 3줄로 교체:

```python
import click
import typer
from typer.core import TyperGroup
```

(`from __future__ import annotations` 이미 존재 — 어노테이션 string화됨. `Any` 는 이미 `from typing import TYPE_CHECKING, Any` 로 import됨.)

- [ ] **Step 4: 기존 20개 `typer.Typer(` 호출 사이트를 `_typer(` 로 교체**

⚠️ **순서 중요**: 팩토리(Step 5)를 추가하기 **전에** 실행한다. 지금은 `typer.Typer(` 가 20개 호출 사이트에만 존재하므로 일괄 치환이 안전하다. 팩토리를 먼저 추가하면 팩토리 내부 `typer.Typer(**kwargs)` 까지 치환돼 무한 재귀가 된다.

Run:
```bash
sed -i '' 's/typer\.Typer(/_typer(/g' src/anvyc/cli.py
grep -c "_typer(" src/anvyc/cli.py    # 기대: 20 (호출 사이트)
grep -c "typer\.Typer(" src/anvyc/cli.py  # 기대: 0
```
Expected: `_typer(` 20개, `typer.Typer(` 0개.

- [ ] **Step 5: `HelpAliasGroup` + `_typer()` 팩토리 추가**

`src/anvyc/cli.py` 에서 루트 앱 정의 `app = _typer(` (Step 4 후, 구 line 100) **바로 위**에 아래 블록을 삽입:

```python
class HelpAliasGroup(TyperGroup):
    """그룹 경로 끝의 `help` 토큰을 `--help` 와 동일하게 처리한다.

    동명의 실제 명령이 있으면 그쪽이 우선(super 먼저). 그 외 미존재 명령은
    기존 'No such command' 에러를 유지한다. 리프 Command 는 비대상.
    """

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        cmd = super().get_command(ctx, cmd_name)
        if cmd is None and cmd_name == "help":
            click.echo(ctx.get_help())
            ctx.exit()
        return cmd


def _typer(**kwargs: Any) -> typer.Typer:
    """anvyc 표준 Typer 앱 — HelpAliasGroup 을 기본 그룹 클래스로 강제."""
    kwargs.setdefault("cls", HelpAliasGroup)
    return typer.Typer(**kwargs)
```

검증:
```bash
grep -c "typer\.Typer(" src/anvyc/cli.py  # 기대: 1 (팩토리 내부만)
grep -c "_typer(" src/anvyc/cli.py        # 기대: 21 (호출 20 + def 1)
```

- [ ] **Step 6: import 정렬 + 포맷 (ruff)**

Run: `ruff check --fix src/anvyc/cli.py && ruff format src/anvyc/cli.py && ruff check src/anvyc/cli.py tests/unit/test_help_alias.py`
Expected: `All checks passed!` (import 순서 자동 정렬 포함).

- [ ] **Step 7: 신규 테스트 실행 → 통과 확인**

Run: `pytest tests/unit/test_help_alias.py -v`
Expected: 6개 테스트 모두 **PASS**.

- [ ] **Step 8: 회귀 — 기존 help/aws 테스트 통과 확인**

Run: `pytest tests/unit/test_cli_help_panels.py tests/unit/test_aws_profile_cli.py -v`
Expected: 모두 **PASS** (루트 panel·aws profile 동작 무회귀).

- [ ] **Step 9: 타입 체크**

Run: `mypy src/anvyc/cli.py`
Expected: 신규 코드 관련 에러 0 (`Success` 또는 기존과 동일한 결과 — 신규 라인발 에러 없음).

- [ ] **Step 10: 커밋**

```bash
git add src/anvyc/cli.py tests/unit/test_help_alias.py
git commit -m "feat(cli): 전역 help 단어 별칭 — anvyc … help = --help (HelpAliasGroup)"
```

---

## Task 2: 문서 업데이트 (README / DESIGN)

**Files:**
- Modify: `README.md` (명령 사용 예시 섹션)
- Modify: `DESIGN.md` (CLI 컴포넌트 메모)

- [ ] **Step 1: README 에 help 단어 별칭 안내 추가**

`README.md` 에서 명령 사용 예시/도움말 관련 섹션을 찾아(예: `anvyc --help` 가 언급된 곳) 아래 한 줄을 인접 추가:

```markdown
> 팁: 어느 그룹 레벨에서든 경로 끝에 `help` 단어를 붙이면 `--help` 와 동일하게 동작합니다 — 예: `anvyc aws profile help` = `anvyc aws profile --help` (리프 명령은 `--help` 만 지원).
```

배치 위치를 찾기 위해:
```bash
grep -n "\-\-help\|도움말\|사용 예시\|Usage" README.md | head
```

- [ ] **Step 2: DESIGN 에 컴포넌트 메모 추가**

`DESIGN.md` 의 CLI(`cli.py`) 구조를 설명하는 섹션에 아래 항목을 추가:

```markdown
- **`HelpAliasGroup` / `_typer()`** (`cli.py`): 모든 Typer 그룹의 기본 클래스를 `HelpAliasGroup` 로 강제하는 팩토리. 그룹 경로 끝의 `help` 단어를 `--help` 와 동일 처리(전역 help 단어 별칭). 리프 Command 는 비대상, 동명 실제 명령은 우선.
```

배치 위치를 찾기 위해:
```bash
grep -n "cli.py\|Typer\|CLI 구조\|entrypoint" DESIGN.md | head
```

- [ ] **Step 3: 문서 렌더 확인 (선택)**

Run: `grep -n "help 단어\|HelpAliasGroup" README.md DESIGN.md`
Expected: 각 파일에 추가한 라인이 노출.

- [ ] **Step 4: 커밋**

```bash
git add README.md DESIGN.md
git commit -m "docs: 전역 help 단어 별칭 (anvyc … help) 사용법/컴포넌트 메모"
```

---

## 최종 검증 (전체)

- [ ] **전체 테스트 스위트**

Run: `pytest -q`
Expected: 전체 PASS (신규 6개 포함, 회귀 0).

- [ ] **수동 스모크 (editable 설치 기준)**

Run:
```bash
anvyc help >/dev/null && echo "root ok"
anvyc aws help >/dev/null && echo "aws ok"
anvyc aws profile help >/dev/null && echo "profile ok"
anvyc aws bogus; echo "exit=$?  (기대: 2)"
```
Expected: `root ok` / `aws ok` / `profile ok` 출력, 마지막은 `No such command` + `exit=2`.

---

## Self-Review 체크 (작성자 기록)

- **Spec coverage**: 목표 3항목(전역 help 별칭, 단일 컴포넌트+팩토리, 무회귀) → Task 1 Step 1–10 이 모두 커버. 문서(spec §9) → Task 2. Non-goals(리프/`-h`/no-args/실제 help 명령)는 구현하지 않음 — 리프 경계는 Task 1 Step 1 의 `test_leaf_command_help_is_argument_not_alias` 로 명시 가드.
- **Placeholder scan**: 모든 step 에 실제 코드/명령/기대 출력 포함. TBD/TODO 없음.
- **Type consistency**: `HelpAliasGroup.get_command(self, ctx, cmd_name)` 시그니처는 Click `Group.get_command` 와 일치(override 안전). 팩토리 `_typer(**kwargs)` ↔ 호출부 키워드 인자 사용 일관. `cls` 키워드는 typer 0.26.2 `Typer.__init__` 지원 확인.
- **sed footgun**: 팩토리 추가(Step 5) 전에 치환(Step 4) — 무한 재귀 회피. grep 카운트로 검증.
