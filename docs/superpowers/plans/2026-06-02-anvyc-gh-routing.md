# `anvyc gh` Race-immune Account 라우팅 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `anvyc gh <args>` subcommand 을 추가해, cwd repo 의 origin SSH alias 가 인코딩한 account 의 토큰을 `GH_TOKEN` 으로 주입하여 `gh` 를 실행한다(전역 active account 무관 → 동시 세션 race 면역).

**Architecture:** 신규 `core/gh_route.py` 가 (a) cwd 에서 origin SSH alias 도출(`utils/git_remote.py` 재사용) (b) `gh auth token --user <account>` 로 토큰 취득 (c) `GH_TOKEN` env 주입 후 `gh` exec 한다. `cli.py` 에 Typer passthrough 커맨드를 얇게 얹는다.

**Tech Stack:** Python 3, Typer(CLI), pytest, gh CLI 2.92+ (`gh auth token --user`).

**Spec:** `docs/superpowers/specs/2026-06-02-anvyc-gh-routing-design.md`

---

## File Structure

- **Create** `src/anvyc/core/gh_route.py` — `resolve_account(start) -> str|None`, `run_gh(account, args) -> int`, `GhRouteError`
- **Modify** `src/anvyc/cli.py` — Typer passthrough 커맨드 `gh` 추가(`PANEL_EXTERNAL`)
- **Create** `tests/unit/test_gh_route.py` — `resolve_account` / `run_gh` 단위 테스트
- **Create** `tests/unit/test_gh_cli.py` — `anvyc gh` 커맨드 와이어링(CliRunner)

작업 브랜치: `feat/gh-routing-subcommand` (이미 생성, 스펙 커밋 `a1822f2` 포함). 테스트: `python3 -m pytest tests/unit/test_gh_route.py tests/unit/test_gh_cli.py -v` (repo 루트에서).

**rule 25 채택(rbr 1줄)은 별도 PR — 본 계획 범위 밖(spec §8). 마지막에 follow-up 으로 안내.**

---

### Task 1: `resolve_account` — origin SSH alias 도출 (TDD)

**Files:**
- Create: `src/anvyc/core/gh_route.py`
- Test: `tests/unit/test_gh_route.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/test_gh_route.py` 생성:

```python
"""anvyc gh_route 단위 테스트 (race-immune account 라우팅)."""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from anvyc.core import gh_route


def _write_git_config(repo: Path, body: str) -> Path:
    g = repo / ".git"
    g.mkdir(parents=True, exist_ok=True)
    (g / "config").write_text(textwrap.dedent(body))
    return repo


def test_resolve_account_from_ssh_alias(tmp_path: Path) -> None:
    repo = _write_git_config(tmp_path, """\
        [remote "origin"]
            url = git@github.com-16bitdo:16bitdo/anvyc.git
    """)
    assert gh_route.resolve_account(repo) == "16bitdo"


def test_resolve_account_heisgone_org_repo(tmp_path: Path) -> None:
    repo = _write_git_config(tmp_path, """\
        [remote "origin"]
            url = git@github.com-heisgone:whatap/open-scripts.git
    """)
    assert gh_route.resolve_account(repo) == "heisgone"


def test_resolve_account_none_for_plain_remote(tmp_path: Path) -> None:
    repo = _write_git_config(tmp_path, """\
        [remote "origin"]
            url = https://github.com/owner/x.git
    """)
    assert gh_route.resolve_account(repo) is None


def test_resolve_account_none_without_origin(tmp_path: Path) -> None:
    repo = _write_git_config(tmp_path, """\
        [remote "upstream"]
            url = git@github.com-16bitdo:16bitdo/x.git
    """)
    assert gh_route.resolve_account(repo) is None


def test_resolve_account_walks_up_from_subdir(tmp_path: Path) -> None:
    repo = _write_git_config(tmp_path, """\
        [remote "origin"]
            url = git@github.com-16bitdo:16bitdo/anvyc.git
    """)
    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)
    assert gh_route.resolve_account(sub) == "16bitdo"


def test_resolve_account_none_when_no_git(tmp_path: Path) -> None:
    assert gh_route.resolve_account(tmp_path) is None
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/edward/dev/anvyc && python3 -m pytest tests/unit/test_gh_route.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'anvyc.core.gh_route'` (또는 import 에러).

- [ ] **Step 3: 구현** — `src/anvyc/core/gh_route.py` 생성:

```python
"""`anvyc gh` — race-immune gh account 라우팅.

cwd repo 의 origin remote SSH alias(github.com-<account>)가 인코딩한 account 의 토큰을
`gh auth token --user` 로 추출해 GH_TOKEN env 로 주입하여 gh 를 실행한다. 전역 active
account 를 건드리지 않아 동시 세션 race 면역.
spec: docs/superpowers/specs/2026-06-02-anvyc-gh-routing-design.md
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from anvyc.utils.git_remote import parse_git_config


class GhRouteError(RuntimeError):
    """account 도출 불가 / 토큰 취득 실패 / gh 미설치 — 비0 exit 로 변환."""


def resolve_account(start: Path) -> str | None:
    """start 에서 .git 디렉터리를 상위로 탐색 → origin remote 의 ssh_alias(=account).

    origin 없음 / alias 없는 plain remote / .git 없음 → None.
    """
    cur = Path(start).resolve()
    for d in (cur, *cur.parents):
        git_dir = d / ".git"
        if git_dir.is_dir():
            for remote in parse_git_config(git_dir):
                if remote.name == "origin":
                    return remote.ssh_alias
            return None
    return None
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/edward/dev/anvyc && python3 -m pytest tests/unit/test_gh_route.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/edward/dev/anvyc
git add src/anvyc/core/gh_route.py tests/unit/test_gh_route.py
git commit -m "feat(gh-route): resolve_account — origin SSH alias 도출"
```

---

### Task 2: `_token_for` + `run_gh` — 토큰 주입 실행 (TDD)

**Files:**
- Modify: `src/anvyc/core/gh_route.py`
- Test: `tests/unit/test_gh_route.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/unit/test_gh_route.py` 끝에 추가:

```python
def test_token_for_returns_stdout(monkeypatch) -> None:
    def fake_run(cmd, **kw):
        assert cmd == ["gh", "auth", "token", "--user", "16bitdo"]
        return subprocess.CompletedProcess(cmd, 0, stdout="ghp_FAKE\n", stderr="")
    monkeypatch.setattr(gh_route.subprocess, "run", fake_run)
    assert gh_route._token_for("16bitdo") == "ghp_FAKE"


def test_token_for_raises_on_failure(monkeypatch) -> None:
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not logged in")
    monkeypatch.setattr(gh_route.subprocess, "run", fake_run)
    try:
        gh_route._token_for("nobody")
        assert False, "expected GhRouteError"
    except gh_route.GhRouteError as e:
        assert "nobody" in str(e)


def test_run_gh_injects_token_and_passes_args(monkeypatch) -> None:
    calls = []
    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        if cmd[:3] == ["gh", "auth", "token"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="ghp_FAKE\n", stderr="")
        return subprocess.CompletedProcess(cmd, 7)  # gh exec exit code
    monkeypatch.setattr(gh_route.subprocess, "run", fake_run)

    code = gh_route.run_gh("16bitdo", ["pr", "create", "--title", "x"])

    assert code == 7
    assert calls[0][0] == ["gh", "auth", "token", "--user", "16bitdo"]
    exec_cmd, exec_kw = calls[1]
    assert exec_cmd == ["gh", "pr", "create", "--title", "x"]
    assert exec_kw["env"]["GH_TOKEN"] == "ghp_FAKE"   # 토큰 env 주입
    assert "capture_output" not in exec_kw or exec_kw["capture_output"] is False  # stdio passthrough
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/edward/dev/anvyc && python3 -m pytest tests/unit/test_gh_route.py -k 'token or run_gh' -v`
Expected: FAIL — `AttributeError: module 'anvyc.core.gh_route' has no attribute '_token_for'` / `run_gh`.

- [ ] **Step 3: 구현** — `src/anvyc/core/gh_route.py` 의 `resolve_account` 함수 **다음**에 추가:

```python
def _token_for(account: str) -> str:
    """`gh auth token --user <account>` → 토큰 문자열. 실패 시 GhRouteError.

    토큰은 반환만 한다 — 절대 출력/로그하지 않는다.
    """
    try:
        cp = subprocess.run(
            ["gh", "auth", "token", "--user", account],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise GhRouteError("gh 가 설치되어 있지 않습니다.") from e
    if cp.returncode != 0 or not cp.stdout.strip():
        raise GhRouteError(
            f"account '{account}' 의 gh 토큰을 얻지 못했습니다 "
            f"(미인증? `gh auth login` 또는 `gh auth switch --user {account}` 로 추가)."
        )
    return cp.stdout.strip()


def run_gh(account: str, args: list[str]) -> int:
    """account 토큰을 GH_TOKEN 으로 주입하여 `gh <args>` 실행. gh 의 exit code 반환.

    child gh 는 stdin/stdout/stderr 를 상속(passthrough). 토큰은 env 로만 전달(argv 금지).
    """
    token = _token_for(account)
    env = dict(os.environ)
    env["GH_TOKEN"] = token
    try:
        cp = subprocess.run(["gh", *args], env=env)
    except FileNotFoundError as e:
        raise GhRouteError("gh 가 설치되어 있지 않습니다.") from e
    return cp.returncode
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/edward/dev/anvyc && python3 -m pytest tests/unit/test_gh_route.py -v`
Expected: PASS (9 tests — Task 1 의 6 + 신규 3).

- [ ] **Step 5: Commit**

```bash
cd /Users/edward/dev/anvyc
git add src/anvyc/core/gh_route.py tests/unit/test_gh_route.py
git commit -m "feat(gh-route): run_gh — GH_TOKEN 주입 실행(race-immune)"
```

---

### Task 3: `anvyc gh` 커맨드 와이어링 (TDD, CliRunner)

**Files:**
- Modify: `src/anvyc/cli.py` (`gh` 커맨드 추가)
- Test: `tests/unit/test_gh_cli.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/test_gh_cli.py` 생성:

```python
"""anvyc gh CLI 와이어링 테스트."""
from __future__ import annotations

from typer.testing import CliRunner

from anvyc import cli
from anvyc.cli import app

runner = CliRunner()


def test_gh_passes_args_and_returns_code(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr("anvyc.core.gh_route.resolve_account", lambda start: "16bitdo")

    def fake_run_gh(account, args):
        seen["account"] = account
        seen["args"] = args
        return 0
    monkeypatch.setattr("anvyc.core.gh_route.run_gh", fake_run_gh)

    result = runner.invoke(app, ["gh", "pr", "create", "--title", "x"])
    assert result.exit_code == 0
    assert seen["account"] == "16bitdo"
    assert seen["args"] == ["pr", "create", "--title", "x"]


def test_gh_exits_2_when_account_unresolved(monkeypatch) -> None:
    monkeypatch.setattr("anvyc.core.gh_route.resolve_account", lambda start: None)
    result = runner.invoke(app, ["gh", "pr", "list"])
    assert result.exit_code == 2
    assert "account" in result.output.lower()


def test_gh_propagates_exit_code(monkeypatch) -> None:
    monkeypatch.setattr("anvyc.core.gh_route.resolve_account", lambda start: "16bitdo")
    monkeypatch.setattr("anvyc.core.gh_route.run_gh", lambda account, args: 7)
    result = runner.invoke(app, ["gh", "api", "x"])
    assert result.exit_code == 7
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/edward/dev/anvyc && python3 -m pytest tests/unit/test_gh_cli.py -v`
Expected: FAIL — `gh` 커맨드 미정의 → exit_code 2(Typer "No such command") 또는 유사. (account=16bitdo 단언 실패 / 출력 불일치.)

- [ ] **Step 3: 구현** — `src/anvyc/cli.py` 에서 기존 `@app.command(rich_help_panel=PANEL_EXTERNAL)` 커맨드(라인 552 부근) **바로 위 또는 아래**에 신규 커맨드를 추가한다(다른 `@app.command` 정의들과 같은 최상위 레벨):

```python
@app.command(
    rich_help_panel=PANEL_EXTERNAL,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def gh(ctx: typer.Context) -> None:
    """cwd repo 의 origin account 로 `gh` 실행 (race-immune 토큰 주입).

    예: `anvyc gh pr create --title X`. account 는 origin remote 의 SSH alias
    (github.com-<account>) 에서 도출 — 전역 active account 를 건드리지 않는다.
    """
    from anvyc.core.gh_route import GhRouteError, resolve_account, run_gh

    account = resolve_account(Path.cwd())
    if account is None:
        console.print(
            "[red]anvyc gh: cwd 의 origin remote 에서 account 를 도출할 수 없습니다 "
            "(SSH alias 'github.com-<account>' remote 필요). bare gh 를 쓰거나 account 를 확인하세요.[/red]"
        )
        raise typer.Exit(code=2)
    try:
        code = run_gh(account, list(ctx.args))
    except GhRouteError as e:
        console.print(f"[red]anvyc gh: {escape(str(e))}[/red]")
        raise typer.Exit(code=2)
    raise typer.Exit(code=code)
```

(참고: `console`(L180), `escape`(rich.markup), `Path`, `typer` 모두 cli.py 에 이미 import/정의되어 있음 — 추가 import 불필요.)

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/edward/dev/anvyc && python3 -m pytest tests/unit/test_gh_cli.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: 통합 스모크(read-only, 실 repo)** — anvyc 클론에서 account 도출+gh 실행이 실제로 되는지(부작용 없는 read-only):

Run: `cd /Users/edward/dev/anvyc && python3 -m anvyc gh api user --jq .login`
Expected: `16bitdo` 출력(cwd=anvyc 의 origin alias 계정). 에러 시 account 도출/토큰 메시지 확인.

- [ ] **Step 6: Commit**

```bash
cd /Users/edward/dev/anvyc
git add src/anvyc/cli.py tests/unit/test_gh_cli.py
git commit -m "feat(cli): anvyc gh — race-immune gh passthrough 커맨드"
```

---

### Task 4: 전체 검증 + PR

**Files:** (없음 — 검증/PR)

- [ ] **Step 1: 전체 테스트 + 타입 + 스코프**

Run:
```bash
cd /Users/edward/dev/anvyc
python3 -m pytest tests/unit/test_gh_route.py tests/unit/test_gh_cli.py -v 2>&1 | tail -5
git diff --name-only main...HEAD
```
Expected: 테스트 PASS(12) · diff = `docs/.../specs/...`, `docs/.../plans/...`, `src/anvyc/core/gh_route.py`, `src/anvyc/cli.py`, `tests/unit/test_gh_route.py`, `tests/unit/test_gh_cli.py`.

- [ ] **Step 2: pre-commit/mypy(있으면) 통과 확인**

Run: `cd /Users/edward/dev/anvyc && python3 -m pytest -q 2>&1 | tail -3`
Expected: 전체 스위트 PASS(기존 테스트 무회귀).

- [ ] **Step 3: Push + PR** (account 라우팅 주의 — 이 작업의 주제 자체)

Run:
```bash
cd /Users/edward/dev/anvyc
git push -u origin feat/gh-routing-subcommand
git ls-remote origin refs/heads/feat/gh-routing-subcommand
GH_TOKEN=$(gh auth token --user 16bitdo) gh pr create --repo 16bitdo/anvyc --base main \
  --head feat/gh-routing-subcommand \
  --title "feat(cli): anvyc gh — race-immune gh account 라우팅" \
  --body "cwd origin SSH alias 의 account 토큰을 GH_TOKEN 으로 주입해 gh 실행 → 전역 active account race 면역. spec/plan: docs/superpowers/. TDD(12 tests)."
```
Expected: PR URL. (PR 생성 자체가 본 기능의 수동판 — `GH_TOKEN=$(gh auth token --user 16bitdo)` 로 account 명시.)

- [ ] **Step 4: PR 메타 검증**

Run: `gh pr view --repo 16bitdo/anvyc --json number,state,files --jq '{n:.number,s:.state,files:[.files[].path]}'`
Expected: OPEN · files 에 gh_route.py / cli.py / 테스트 2 / spec / plan.

---

## Follow-up (별도, 본 계획 범위 밖)

**rbr rule 25 채택 1줄** (spec §8) — `role-based-ruleset` 의 `25-github-ssh-host-selection` 에 *"gh-API write 는 `anvyc gh ...` 로 — race-immune"* 한 줄 추가. **별도 PR**(다른 repo, rbr PR 필수). anvyc 머지·검증 후 진행 권장.

---

## Self-Review

**1. Spec coverage** (spec § → task):
- §3 결정(token-injection/alias/subcommand) → Task 1·2·3 ✓
- §4 아키텍처 → Task 1(alias)·2(token+exec)·3(cli) ✓
- §5 컴포넌트(gh_route.py resolve_account/run_gh, cli.py, git_remote 재사용) → Task 1·2·3 ✓
- §6 에러(silent fallback 금지 → 비0 exit) → Task 3 Step3(account None→exit2)·Task 2(GhRouteError) ✓
- §7 보안(토큰 env-only·미표시) → Task 2 test(`env GH_TOKEN`, argv 아님)·`_token_for` 미출력 ✓
- §8 채택(rule 25) → Follow-up(별도 PR 명시) ✓
- §9 테스트(resolve_account 케이스·run_gh monkeypatch·통합) → Task 1·2 단위 + Task 3 Step5 통합 ✓
- §11 성공기준 → Task 3 Step5(실 account 출력)·Task 4 ✓

**2. Placeholder scan:** 모든 코드 스텝에 완전한 코드. "TBD/적절히" 없음 ✓

**3. Type consistency:** `resolve_account(start)->str|None`, `run_gh(account,args)->int`, `_token_for(account)->str`, `GhRouteError` — Task 1·2·3·테스트 전부 동일 시그니처 ✓. cli `gh(ctx)` 가 `list(ctx.args)` 를 `run_gh` 에 전달(Task 2 args 타입 list[str]과 일치) ✓
