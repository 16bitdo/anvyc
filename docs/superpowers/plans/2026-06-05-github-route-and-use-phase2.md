# `anvyc github route` + `github use` — 라우팅 CRUD Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** owner→account 라우팅 매핑(`anvyc.yaml doctor.gh_owner_accounts`)을 `anvyc github route <list|set|rm>` 로 CRUD 하고, 현재 프로젝트의 `.envrc` `GH_CONFIG_DIR` 를 `anvyc github use [<account>]` 로 작성한다. Phase 1(읽기 전용 뷰)의 **쓰기** 후속.

**Architecture:** 신규 `core/gh_routes_edit.py` 가 `anvyc.yaml` 의 `doctor.gh_owner_accounts` 만 surgical 하게 갱신한다 — `core/project_roots_edit.py` 의 **full-dict round-trip** 패턴(`_load_raw` → dict 수정 → `yaml_io.atomic_write_yaml` + `.bak` + 재검증) 이식. `github route` CLI 는 Phase 1 의 `github` 그룹 아래 `route` 서브그룹으로 붙는다. `github use` 는 `core/project_init.py` 의 `resolve_routing_account` + `write_envrc_gh_routing` 를 재사용(중복 0). 인증/토큰은 일절 다루지 않는다(routing 설정 = 비밀 아님).

**Tech Stack:** Python 3.13, Typer(CLI), PyYAML(`yaml_io`), `pytest`+`typer.testing.CliRunner`.

**Spec:** `docs/superpowers/specs/2026-06-05-anvyc-github-account-and-routing-design.md` (§3 결정·§6.2 라우팅 명령·§9 Phase 2; §12 확정: `github route` / `github use` = Phase 2).

**구현 정밀화 메모(spec 대비)**:
- **중첩 키 = full-dict round-trip 으로 단순화** — `doctor.gh_owner_accounts` 는 `doctor:` 아래 nested dict 다. `project_roots_edit`(top-level `project_roots`)와 달리 nested 지만, 쓰기가 surgical 텍스트가 아니라 **dict round-trip**(`atomic_write_yaml`)이라 `raw.setdefault("doctor", {}).setdefault("gh_owner_accounts", {})[owner] = account` 한 줄이면 된다. (트레이드오프: `anvyc.yaml` 주석은 round-trip 으로 소실 — `config roots/projects` 와 동일한 기존 동작이므로 일관.)
- **config 경로 해석 재사용** — `github route` 는 `config roots` 가 쓰는 `_resolve_roots_target(config, local)`(cli.py) 를 재사용해 동일 `anvyc.yaml` 을 대상으로 한다(`--config`/`--local` 동일 의미). 헬퍼명이 roots 특정이면 일반 이름(`_resolve_config_target`)으로 **rename**(roots 호출부 동시 갱신).
- **`route set` 미로그인 account 허용** — 매핑 대상 account 가 아직 `~/.config/gh-<account>` 에 없어도 매핑은 작성하고 1줄 경고(미래 로그인 대비). spec §8.
- **`use` 의 `.gitignore`/allow** — `.envrc` 작성은 `write_envrc_gh_routing` 재사용. `.gitignore` 보장·`direnv allow` 는 `project init` 의 책임이므로 `use` 는 `.envrc` 작성 + (`--no-allow` 아니면) best-effort `direnv allow` 만. 광범위 스캐폴딩은 `project init` 위임(중복 회피).
- **dry-run diff** — `route set/rm` 은 변경 전/후 `gh_owner_accounts` 매핑의 difflib unified diff 를 미리 보여준다(`--dry-run` 시 출력 후 exit 0, 무변경).

---

## File Structure

**신규 파일**
- `src/anvyc/core/gh_routes_edit.py` — `@dataclass RoutesEditResult`, `set_route(config_path, owner, account, *, make_backup=True)`, `remove_route(config_path, owner, *, make_backup=True)`, 내부 `_load_raw`/`_write`(project_roots_edit `_write_roots` 이식: `.bak` + `atomic_write_yaml` + 재파싱 검증).
- `tests/unit/test_gh_routes_edit.py`, `tests/unit/test_github_route_cli.py`, `tests/unit/test_github_use_cli.py`

**수정 파일**
- `src/anvyc/cli.py` — `github_route_app` 등록 + `route list/set/rm` + `github use`. (`_resolve_roots_target` → `_resolve_config_target` rename + roots 호출부 갱신.)
- `README.md`, `docs/multi-account.md`, `DESIGN.md` — `github route`/`use` 사용 예.

**시그니처**
```
# core/gh_routes_edit.py
@dataclass
class RoutesEditResult:
    action: str                 # "set" | "remove"
    owner: str
    account: str | None = None
    before: dict[str, str] = field(default_factory=dict)
    after: dict[str, str] = field(default_factory=dict)
    written: bool = False
    config_path: Path | None = None
    backup_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
set_route(config_path: Path, owner: str, account: str, *, make_backup: bool = True) -> RoutesEditResult
remove_route(config_path: Path, owner: str, *, make_backup: bool = True) -> RoutesEditResult
```

---

## Task 1: `core/gh_routes_edit.py` — anvyc.yaml `doctor.gh_owner_accounts` 안전쓰기

**Files:** Create `src/anvyc/core/gh_routes_edit.py`, Test `tests/unit/test_gh_routes_edit.py`

- [ ] **Step 1: 실패 테스트** — tmp `anvyc.yaml`(있는 것/빈 것) 대상:
  - `set_route` 신규 owner 추가 → `after[owner]==account`, 파일 재로드 시 반영, `.bak` 생성.
  - `set_route` 기존 owner 치환 → 값 교체, 타 owner 보존.
  - `set_route` 빈/`doctor` 없는 yaml → `doctor.gh_owner_accounts` 생성.
  - `remove_route` 존재 owner → 제거, 타 owner 보존, `written=True`.
  - `remove_route` 미존재 owner → `written=False`, 경고/무변경.
  - 쓰기 후 `load_anvyc_config(path)` 가 예외 없이 로드(재검증).
- [ ] **Step 2: 실패 확인** — `ModuleNotFoundError`.
- [ ] **Step 3: 구현** — `project_roots_edit` 패턴 이식: `_load_raw(config_path)` → `raw.setdefault("doctor", {}).setdefault("gh_owner_accounts", {})` 수정 → `before`/`after` 캡처 → 변경 있을 때만 `.bak`+`atomic_write_yaml` → `load_anvyc_config` 재파싱(실패 시 `.bak` 복구). owner/account 는 식별자만(검증: 빈 문자열 거부).
- [ ] **Step 4: 통과 확인.**
- [ ] **Step 5: 커밋** — `feat(github): gh_routes_edit — doctor.gh_owner_accounts 안전쓰기 (set/remove)`

---

## Task 2: CLI `anvyc github route <list|set|rm>`

**Files:** Modify `src/anvyc/cli.py`, Test `tests/unit/test_github_route_cli.py`

- [ ] **Step 1: 실패 테스트** (`CliRunner`, HOME monkeypatch + tmp anvyc.yaml):
  - `route list [--json]` — 매핑 + 각 account 로그인 여부(`~/.config/gh-<account>` 발견) 표시.
  - `route set <owner> <account> --yes` — 매핑 작성, 재조회 시 반영. `--dry-run` → 무변경 + diff 출력.
  - `route rm <owner> --yes` — 제거. 미존재 owner → 안내(비0 아님 또는 무변경 메시지, spec §8).
  - 미로그인 account `set` → 작성 + 경고 1줄.
- [ ] **Step 2: 실패 확인** — `No such command 'route'`.
- [ ] **Step 3: 구현** — `github_route_app = _typer(name="route", ...)` + `github_app.add_typer(.., "route")`. `_resolve_roots_target`→`_resolve_config_target` rename(roots 호출부 동시 갱신). `set`/`rm` 은 `gh_routes_edit` 호출 + `--dry-run`(difflib diff 미리보기, 무변경 exit 0) + `--yes`(확인 생략) + `.bak`. `list` 는 `load_anvyc_config` 매핑 + `discover_gh_accounts` 로 로그인 여부. 출력 규약 doctor 동일(`escape`).
- [ ] **Step 4: 통과 확인.**
- [ ] **Step 5: 커밋** — `feat(github): anvyc github route list/set/rm — owner→account 매핑 CRUD`

---

## Task 3: CLI `anvyc github use [<account>]`

**Files:** Modify `src/anvyc/cli.py`, Test `tests/unit/test_github_use_cli.py`

- [ ] **Step 1: 실패 테스트** (tmp repo + HOME):
  - `use <account>` → cwd `.envrc` 에 `GH_CONFIG_DIR=$HOME/.config/gh-<account>` 작성(idempotent: 재실행 시 unchanged).
  - `use`(account 생략) + origin ssh alias repo → `resolve_routing_account` 도출 계정으로 작성.
  - `use`(도출 불가: remote 없음 + 매핑 없음) → 명확 에러 + 비0 exit (silent fallback 금지, `anvyc gh` 원칙).
  - `--dry-run` → 무변경.
- [ ] **Step 2: 실패 확인** — `No such command 'use'`.
- [ ] **Step 3: 구현** — `@github_app.command("use")`. account 인자 있으면 사용, 없으면 `resolve_routing_account(Path.cwd(), load_anvyc_config(None).doctor.gh_owner_accounts)`. `write_envrc_gh_routing(cwd/".envrc", account)` 재사용. `--no-allow` 아니면 best-effort `direnv allow`. `--dry-run` 무변경. 토큰 미관여(경로만).
- [ ] **Step 4: 통과 확인.**
- [ ] **Step 5: 커밋** — `feat(github): anvyc github use — cwd .envrc GH_CONFIG_DIR 작성`

---

## Task 4: 문서 + 회귀/lint (orchestrator)

- [ ] **Step 1**: `README.md` §11 + `docs/multi-account.md` §2.1 에 `github route`/`use` 추가. `DESIGN.md` §6.1 `github` 행 갱신(route/use 포함).
- [ ] **Step 2: 회귀** — `pytest -q` 전체 GREEN. 특히 `config roots/projects`(`_resolve_config_target` rename 영향)·Phase 1 `github account`·`anvyc gh` passthrough 불변.
- [ ] **Step 3: lint/type** — `.venv/bin/ruff check src tests && .venv/bin/mypy src/anvyc`. (cli.py 에 `ruff format` 전체 실행 금지 — 무관한 `project_init` 포맷 creep 유발. 신규/변경 라인만 format-clean 유지.)
- [ ] **Step 4: 커밋** — `docs(github): github route/use 사용 예 + 라우팅 CRUD 경계`

---

## 완료 기준 (Phase 2)

- `github route set/rm` 가 `anvyc.yaml doctor.gh_owner_accounts` 를 `.bak`+재검증 안전쓰기, `--dry-run`/`--yes` 지원.
- `github route list` 매핑 + 로그인 여부 표시.
- `github use [account]` 가 cwd `.envrc` 작성(도출 불가 시 비0 exit).
- 토큰 미관여(routing/설정만). `config roots/projects`·Phase 1·`anvyc gh` 회귀 0. `ruff`/`mypy` GREEN.
- 정리 후속(별도): `creds.py`↔`gh_probe.py` 만료 파서 중복 통합(Phase 1 에서 이월).
