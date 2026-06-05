# `anvyc … help` — 전역 `help` 단어 별칭 설계

- **날짜**: 2026-06-05
- **상태**: 승인됨 (구현 대기)
- **프로젝트**: anvyc (L2-environment)
- **관련**: `cli.py`(Typer 앱/서브앱 20개 정의), `tests/unit/test_cli_help_panels.py`(help 출력 검증 선례)

## 1. 배경 / 문제

anvyc CLI 는 Typer(0.26.2) / Click(8.4.1) 기반의 다단계 서브커맨드 트리다(`anvyc aws profile show` 등). 도움말은 Typer 기본인 **`--help` 플래그**로만 노출된다.

사용자가 명령 경로 끝에 `help` 를 **단어**로 붙여 도움을 받으려 하면 막힌다. 현재 동작(관측):

```
$ anvyc aws profile help
Usage: anvyc aws profile [OPTIONS] COMMAND [ARGS]...
╭─ Error ─────────────────────────────────────────╮
│ No such command 'help'.                          │
╰─────────────────────────────────────────────────╯
```

`git help`, `npm help`, `kubectl help` 등 다수 CLI 가 `<path> help` 를 `--help` 별칭으로 지원하는 것과 달리, anvyc 는 사용자가 정확히 `--help` 플래그를 기억해야만 한다. "마지막으로 입력하던 그룹"에 대한 도움을 자연스러운 단어로 받을 수 없다.

## 2. 목표 / Non-goals

**목표**:
- 모든 **그룹 레벨**에서 경로 끝의 `help` 단어를 `--help` 와 동일하게 처리한다.
  - `anvyc help` = `anvyc --help`
  - `anvyc aws help` = `anvyc aws --help`
  - `anvyc aws profile help` = `anvyc aws profile --help`
- 단일 컴포넌트 + 팩토리로 **전역 일관** 적용(향후 신규 그룹 자동 포함, 누락 위험 최소화).
- 기존 동작·출력(panel, rich 렌더, `--help`, 에러 메시지) **무변경**.

**Non-goals (YAGNI)**:
- **리프 명령**(`@command`, 예: `anvyc aws profile show`)의 `help` 단어 지원 — 제외. 리프 명령 뒤의 `help` 는 그 명령의 **인자**로 전달되며, 리프 도움말은 계속 `--help` 만 지원한다. ("마지막 명령어 = 탐색 중인 그룹" 시나리오를 충족)
- **`-h` 단축 플래그** 추가 — 제외(후속 가능, `context_settings`).
- **no-args 도움말 일관화** — 제외. 중첩 그룹을 인자 없이 호출하면(`anvyc aws profile`) 루트와 달리 `Missing command` 에러가 나는 불일치가 있으나, 이번 범위 밖(별건).
- `help` 라는 **실제 명령** 신규 도입 — 안 함(별칭은 실제 명령이 없을 때만 발동).

## 3. 결정 (승인됨)

| 결정 | 선택 | 근거 |
|------|------|------|
| 적용 방식 | **접근 A — 단일 `HelpAliasGroup` + 팩토리 `_typer()`** | 한 곳 제어·DRY, 신규 그룹 자동 적용. (대안 B: 20곳 `cls=` 명시 → 누락 위험. C: 그룹별 `help` 명령 등록 → 부품 과다) |
| 가로채기 지점 | **`TyperGroup.get_command` 오버라이드** | `super().get_command` 가 먼저라 실제 명령이 우선(안전 precedence). 검증된 동작. |
| 별칭 발동 조건 | `super().get_command(ctx, name) is None and name == "help"` | 실제 `help` 명령이 생겨도 그쪽 우선, 다른 미존재 명령은 기존 에러 유지 |
| 출력 방식 | `click.echo(ctx.get_help()); ctx.exit()` | `--help` 와 동일 렌더(panel·rich 보존), exit 0 |
| 적용 범위 | 그룹 전용(리프 명령 제외) | Typer 는 그룹(Group)에만 `get_command` 존재 — 리프는 자연히 비대상 |

## 4. 아키텍처

신규 컴포넌트 **1개**(클래스) + 헬퍼 **1개**(팩토리), 모두 `src/anvyc/cli.py` 내부.

> **구현 노트 (as-built)**: Typer 0.26.2 는 Click 을 `typer._click` 로 vendoring 하며 `TyperGroup.get_command` 의 부모 시그니처가 `typer._click.core.Context`/`Command` 를 사용한다. 따라서 mypy override 호환을 위해 `import click` 이 아니라 **`import typer._click as click`** 를 쓰고 시그니처에 그 타입을 명시한다(그러면 `# type: ignore[override]` 불필요). 또한 shell completion(`resilient_parsing=True`) 중 별칭 발동을 막기 위해 `and not ctx.resilient_parsing` 가드를 추가한다. 최종 구현:

```python
import typer._click as click  # vendored Click — TyperGroup.get_command 시그니처가 typer._click 타입 (mypy override 호환)
from typer.core import TyperGroup

class HelpAliasGroup(TyperGroup):
    """그룹 경로 끝의 'help' 토큰을 --help 와 동일하게 처리한다.

    실제 동명 명령이 있으면 그쪽이 우선(super 먼저). 그 외 미존재 명령은
    기존 'No such command' 에러를 유지한다. 리프 Command 는 비대상.
    """
    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        cmd = super().get_command(ctx, cmd_name)
        # resilient_parsing(shell completion) 중에는 발동 금지 — 완성 후보 오염 방지.
        if cmd is None and cmd_name == "help" and not ctx.resilient_parsing:
            click.echo(ctx.get_help())
            ctx.exit()
        return cmd

def _typer(**kwargs) -> typer.Typer:
    """anvyc 표준 Typer 앱 — HelpAliasGroup 을 기본 그룹 클래스로 강제."""
    kwargs.setdefault("cls", HelpAliasGroup)
    return typer.Typer(**kwargs)
```

**배선 변경**: `cli.py` 의 모든 `typer.Typer(...)` 호출(루트 `app` 포함 총 **20개**: `app`, `git_app`, `sops_app`, `config_app`, `roots_app`, `projects_app`, `tools_app`, `project_app`, `aws_app`, `aws_profile_app`, `snapshot_app`, `creds_app`, `sync_app`, `sync_conflict_app`, `workctx_app`, `cost_app`, `runs_app`, `secret_app`, `mcp_app`, `guard_app`)을 모두 `_typer(...)` 로 교체한다. (구현 시 `grep -c "typer.Typer(" src/anvyc/cli.py` 로 누락 없음 확인.) `setdefault` 라 기존에 `cls` 를 명시한 앱이 있으면 보존(현재 없음).

## 5. 데이터 흐름

```
$ anvyc aws profile help
  → Click: 루트 group(app) resolve "aws" → aws group resolve "profile"
  → profile group(HelpAliasGroup).get_command(ctx, "help")
       super().get_command → None ('help' 명령 없음)
       name == "help"      → click.echo(ctx.get_help()); ctx.exit()
  → profile 그룹 --help 와 동일 출력, exit 0
```

리프 경로(비대상):
```
$ anvyc aws profile show help
  → show 는 Command(그룹 아님) → get_command 미존재 → "help" 는 show 의 인자
  → 기존 동작(인자 처리/에러) 그대로
```

## 6. 동작 정의 (수용 기준)

| 입력 | 기대 결과 |
|------|-----------|
| `anvyc help` | 루트 도움말(= `anvyc --help`), exit 0 |
| `anvyc aws help` | aws 그룹 도움말, exit 0 |
| `anvyc aws profile help` | profile 그룹 도움말(서브커맨드 목록 포함), exit 0 |
| `anvyc aws profile help` vs `… --help` | 정규화(ANSI 제거·폭 고정) 후 본문 동등 |
| `anvyc aws bogus` | 기존대로 `No such command 'bogus'` 에러(변경 없음) |
| `anvyc aws profile show help` | `show` 의 인자로 `help` 전달(별칭 비발동) |
| `anvyc --help` / 기존 panel 출력 | 무변경(회귀 없음) |

## 7. 에러 처리 / 엣지

- **실제 `help` 명령 충돌**: `super()` 우선이라 안전. 현재 그런 명령 없음.
- **`help` 뒤 추가 토큰**(`… profile help foo`): Click 이 명령명 `help` 를 먼저 해석 → help 출력 후 `ctx.exit()`, 잔여 토큰 무시. 수용.
- **rich/panel 렌더**: `HelpAliasGroup` 이 `TyperGroup` 의 서브클래스라 panel·색상 렌더 보존. `ctx.get_help()` 는 `--help` 와 동일 경로.

## 8. 테스트 (TDD)

신규 `tests/unit/test_help_alias.py` (기존 `test_cli_help_panels.py` 의 ANSI 정규화 패턴 재사용):

1. `["help"]`, `["aws","help"]`, `["aws","profile","help"]` → 각 exit 0 + `Usage:` 포함 + 해당 레벨의 알려진 서브커맨드명 포함.
2. `["aws","profile","help"]` 출력 ≡ `["aws","profile","--help"]` 출력(정규화 후 동등).
3. 회귀 가드: `["aws","bogus"]` → exit ≠ 0, `No such command` 포함.
4. 리프 경계: `["aws","profile","show","help"]` → 별칭 비발동(help 출력 아님; show 의 인자/에러 경로).
5. 기존 `test_cli_help_panels.py` 전체 통과 유지(루트 panel 무회귀).

## 9. 문서 / 영향

- `README.md`: 명령 사용 예시에 `help` 단어 별칭 한 줄 추가(`anvyc aws profile help` ≈ `--help`).
- `DESIGN.md`: `HelpAliasGroup` / `_typer()` 컴포넌트 메모(전역 help 별칭).
- 영향 범위: `cli.py` 배선 + 신규 테스트만. 런타임 의존성 추가 없음(`click`/`typer.core` 는 기존 의존성).

## 10. 단계 / 브랜치

- 단일 PR. 브랜치 `feat/cli-help-word-alias`(컷 완료).
- 머지 방식·리뷰어는 프로젝트 branch 전략(`metadata/branch-strategies.yaml`) 준수.
