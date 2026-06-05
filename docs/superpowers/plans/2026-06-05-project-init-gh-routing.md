# `anvyc project init` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `anvyc project init` 로 origin 기준 gh 계정을 도출해 대화형 확인 후 per-project `.envrc`(GH_CONFIG_DIR) 라우팅을 스캐폴딩한다 — `project doctor` #3(감지)의 교정(remediation) 측면.

**Architecture:** 도출은 기존 `gh_route.resolve_account`(origin ssh alias) 재사용, account↔dir 변환은 신규 공유 헬퍼 `gh_config_dir_for_account`(doctor #3 도 사용 → 발산 방지). 쓰기 로직(.envrc 멱등 inject / .gitignore / 로그인 검증)은 순수 함수로 `core/project_init.py` 에 격리하고, `cli.py` 의 `project init` 커맨드는 prompt/validation/direnv allow/요약만 오케스트레이션.

**Tech Stack:** Python 3.13, typer(+`typer.testing.CliRunner`), rich, pytest, ruff, mypy. 실행: `~/dev/anvyc/.venv/bin/python -m …`.

**Spec:** `docs/superpowers/specs/2026-06-05-project-init-gh-routing-design.md`

---

## File Structure

| 파일 | 책임 | 변경 |
|------|------|------|
| `src/anvyc/core/project_info.py` | account↔GH_CONFIG_DIR convention SoT | **수정**: `gh_config_dir_for_account` 추가(`_derive_gh_account` 역함수) |
| `src/anvyc/core/project_doctor.py` | project 정합성 감지(#3 포함) | **수정**: `_check_gh_account_routing` 가 공유 헬퍼 사용 |
| `src/anvyc/core/project_init.py` | 스캐폴딩 순수 로직(도출/inject/gitignore/로그인) | **신규** |
| `src/anvyc/cli.py` | `project init` 커맨드(오케스트레이션) | **수정**: `@project_app.command("init")` 추가 |
| `tests/unit/test_project_init.py` | 순수 함수 단위 테스트 | **신규** |
| `tests/unit/test_project_init_cli.py` | CLI 통합(CliRunner) | **신규** |
| `docs/multi-account.md` | 신규 프로젝트 셋업 안내 | **수정**(Task 8) |

**테스트 실행(공통):** `cd ~/dev/anvyc && .venv/bin/python -m pytest <경로> -v`

---

## Task 1: `gh_config_dir_for_account` 공유 헬퍼

**Files:**
- Modify: `src/anvyc/core/project_info.py` (`_derive_gh_account` 바로 아래, line 56 부근)
- Test: `tests/unit/test_project_init.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/test_project_init.py` 신규 생성

```python
"""anvyc project_init 순수 로직 단위 테스트."""
from __future__ import annotations

from pathlib import Path

from anvyc.core.project_info import _derive_gh_account, gh_config_dir_for_account


def test_gh_config_dir_for_account() -> None:
    assert gh_config_dir_for_account("16bitdo") == "$HOME/.config/gh-16bitdo"
    assert gh_config_dir_for_account("heisgone") == "$HOME/.config/gh-heisgone"


def test_gh_config_dir_round_trips_with_derive() -> None:
    # 역함수 관계: account → dir → account
    assert _derive_gh_account(gh_config_dir_for_account("heisgone")) == "heisgone"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init.py -v`
Expected: FAIL — `ImportError: cannot import name 'gh_config_dir_for_account'`

- [ ] **Step 3: 최소 구현** — `src/anvyc/core/project_info.py` `_derive_gh_account` 함수 끝(line 55) 다음에 추가

```python
def gh_config_dir_for_account(account: str) -> str:
    """gh account 이름 → `.envrc` 에 쓸 GH_CONFIG_DIR 리터럴 값.

    convention: `<account>` → `$HOME/.config/gh-<account>` (`_derive_gh_account` 의 역함수).
    `$HOME` 는 **리터럴로 보존** — direnv 가 확장하고, statusline grep / `_parse_envrc` 는
    basename(`gh-<account>`)만 보므로 portable 해야 한다.
    """
    return f"$HOME/.config/gh-{account}"
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/project_info.py tests/unit/test_project_init.py
git commit -m "feat(project): gh_config_dir_for_account 공유 헬퍼 (account→GH_CONFIG_DIR)"
```

---

## Task 2: doctor #3 가 공유 헬퍼 사용 (출력 불변 리팩터)

**Files:**
- Modify: `src/anvyc/core/project_doctor.py:26`(import), `:134-136`·`:149-151`(suggestion)

- [ ] **Step 1: 기존 doctor 테스트 GREEN 확인 (baseline)**

Run: `.venv/bin/python -m pytest tests/unit/test_project_gh_account.py tests/unit/test_project_doctor_render.py -v`
Expected: PASS (기준선 — 리팩터 후 동일해야 함)

- [ ] **Step 2: import 에 헬퍼 추가** — `project_doctor.py:26`

기존:
```python
from anvyc.core.project_info import ProjectInfo, collect_project_info, expand_envrc_path
```
변경:
```python
from anvyc.core.project_info import (
    ProjectInfo,
    collect_project_info,
    expand_envrc_path,
    gh_config_dir_for_account,
)
```

- [ ] **Step 3: 두 suggestion 을 헬퍼로 (출력 byte-identical)** — `project_doctor.py:134-136`

기존:
```python
                suggestion=(
                    f'.envrc 에 export GH_CONFIG_DIR="$HOME/.config/gh-{alias}" '
                    f"추가 후 direnv allow"
                ),
```
변경:
```python
                suggestion=(
                    f'.envrc 에 export GH_CONFIG_DIR="{gh_config_dir_for_account(alias)}" '
                    f"추가 후 direnv allow"
                ),
```

그리고 `project_doctor.py:149-151`:

기존:
```python
                suggestion=(
                    f'export GH_CONFIG_DIR="$HOME/.config/gh-{alias}" 로 수정 '
                    f"(ssh alias 와 일치)"
                ),
```
변경:
```python
                suggestion=(
                    f'export GH_CONFIG_DIR="{gh_config_dir_for_account(alias)}" 로 수정 '
                    f"(ssh alias 와 일치)"
                ),
```

- [ ] **Step 4: 출력 불변 확인 (동일 테스트 GREEN)**

Run: `.venv/bin/python -m pytest tests/unit/test_project_gh_account.py tests/unit/test_project_doctor_render.py -v`
Expected: PASS — `gh-{alias}` 부분문자열 보존되어 기존 assert 그대로 통과

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/project_doctor.py
git commit -m "refactor(project): doctor #3 가 gh_config_dir_for_account 공유 (출력 불변)"
```

---

## Task 3: `write_envrc_gh_routing` — `.envrc` 멱등 inject

**Files:**
- Create: `src/anvyc/core/project_init.py`
- Test: `tests/unit/test_project_init.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/unit/test_project_init.py` 끝에 append

```python
from anvyc.core.project_init import write_envrc_gh_routing


def test_write_envrc_creates_new_file(tmp_path: Path) -> None:
    envrc = tmp_path / ".envrc"
    status = write_envrc_gh_routing(envrc, "16bitdo")
    assert status == "created"
    assert envrc.read_text() == 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n'


def test_write_envrc_replaces_different_value(tmp_path: Path) -> None:
    envrc = tmp_path / ".envrc"
    envrc.write_text('export GH_CONFIG_DIR="$HOME/.config/gh-none"\n')
    status = write_envrc_gh_routing(envrc, "16bitdo")
    assert status == "replaced"
    assert envrc.read_text() == 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n'


def test_write_envrc_unchanged_when_same(tmp_path: Path) -> None:
    envrc = tmp_path / ".envrc"
    envrc.write_text('export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n')
    assert write_envrc_gh_routing(envrc, "16bitdo") == "unchanged"


def test_write_envrc_adds_to_existing_preserving_others(tmp_path: Path) -> None:
    envrc = tmp_path / ".envrc"
    envrc.write_text('export AWS_PROFILE="dev"\n')
    status = write_envrc_gh_routing(envrc, "16bitdo")
    assert status == "added"
    body = envrc.read_text()
    assert 'export AWS_PROFILE="dev"' in body
    assert 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"' in body
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init.py -k write_envrc -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'anvyc.core.project_init'`

- [ ] **Step 3: 모듈 + 함수 구현** — `src/anvyc/core/project_init.py` 신규

```python
"""anvyc project init — per-project gh 라우팅 `.envrc` 스캐폴딩 (순수 로직).

cli.py 의 `project init` 커맨드가 이 함수들을 오케스트레이션한다.
spec: docs/superpowers/specs/2026-06-05-project-init-gh-routing-design.md
"""
from __future__ import annotations

import re
from pathlib import Path

from anvyc.core import gh_route
from anvyc.core.project_info import gh_config_dir_for_account
from anvyc.utils.git_remote import parse_git_config

_GH_LINE_RE = re.compile(r"^[ \t]*export[ \t]+GH_CONFIG_DIR[ \t]*=.*$", re.MULTILINE)


def write_envrc_gh_routing(envrc: Path, account: str) -> str:
    """`.envrc` 에 GH_CONFIG_DIR export 줄을 멱등 주입.

    반환: "created"(파일 신규) / "added"(기존 파일에 줄 추가) /
          "replaced"(기존 GH_CONFIG_DIR 줄 교체) / "unchanged"(이미 동일).
    기존 다른 export 는 보존한다.
    """
    line = f'export GH_CONFIG_DIR="{gh_config_dir_for_account(account)}"'
    if not envrc.exists():
        envrc.write_text(line + "\n", encoding="utf-8")
        return "created"
    text = envrc.read_text(encoding="utf-8")
    m = _GH_LINE_RE.search(text)
    if m:
        if m.group(0).strip() == line:
            return "unchanged"
        envrc.write_text(_GH_LINE_RE.sub(line, text, count=1), encoding="utf-8")
        return "replaced"
    sep = "" if text == "" or text.endswith("\n") else "\n"
    envrc.write_text(text + sep + line + "\n", encoding="utf-8")
    return "added"
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init.py -k write_envrc -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/project_init.py tests/unit/test_project_init.py
git commit -m "feat(project): write_envrc_gh_routing — .envrc GH_CONFIG_DIR 멱등 inject"
```

---

## Task 4: `ensure_gitignore_entry` — `.gitignore` 보장

**Files:**
- Modify: `src/anvyc/core/project_init.py`
- Test: `tests/unit/test_project_init.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/unit/test_project_init.py` 끝에 append

```python
from anvyc.core.project_init import ensure_gitignore_entry


def test_gitignore_created_when_absent(tmp_path: Path) -> None:
    gi = tmp_path / ".gitignore"
    assert ensure_gitignore_entry(gi, ".envrc") is True
    assert gi.read_text() == ".envrc\n"


def test_gitignore_appends_when_missing_entry(tmp_path: Path) -> None:
    gi = tmp_path / ".gitignore"
    gi.write_text("node_modules/\n")
    assert ensure_gitignore_entry(gi, ".envrc") is True
    assert gi.read_text() == "node_modules/\n.envrc\n"


def test_gitignore_noop_when_present(tmp_path: Path) -> None:
    gi = tmp_path / ".gitignore"
    gi.write_text(".env\n.envrc\n")
    assert ensure_gitignore_entry(gi, ".envrc") is False
    assert gi.read_text() == ".env\n.envrc\n"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init.py -k gitignore -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_gitignore_entry'`

- [ ] **Step 3: 구현** — `src/anvyc/core/project_init.py` 끝에 추가

```python
def ensure_gitignore_entry(gitignore: Path, entry: str) -> bool:
    """`.gitignore` 에 `entry` 줄이 없으면 추가. 변경 시 True, 이미 있으면 False.

    `.gitignore` 부재 시 생성. 비교는 줄 단위 strip 일치.
    """
    if gitignore.exists():
        text = gitignore.read_text(encoding="utf-8")
        if entry in (ln.strip() for ln in text.splitlines()):
            return False
        sep = "" if text == "" or text.endswith("\n") else "\n"
        gitignore.write_text(text + sep + entry + "\n", encoding="utf-8")
        return True
    gitignore.write_text(entry + "\n", encoding="utf-8")
    return True
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init.py -k gitignore -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/project_init.py tests/unit/test_project_init.py
git commit -m "feat(project): ensure_gitignore_entry — .envrc gitignore 보장"
```

---

## Task 5: `resolve_routing_account` — origin→account 도출(alias / 매핑 / 불가)

**Files:**
- Modify: `src/anvyc/core/project_init.py`
- Test: `tests/unit/test_project_init.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/unit/test_project_init.py` 끝에 append

```python
import textwrap

from anvyc.core.project_init import resolve_routing_account


def _repo(tmp_path: Path, url: str) -> Path:
    g = tmp_path / ".git"
    g.mkdir(parents=True, exist_ok=True)
    (g / "config").write_text(textwrap.dedent(f"""\
        [remote "origin"]
            url = {url}
    """))
    return tmp_path


def test_resolve_account_from_alias(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "git@github.com-16bitdo:16bitdo/x.git")
    assert resolve_routing_account(repo, {}) == ("16bitdo", "alias")


def test_resolve_account_from_mapping_when_plain_host(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "https://github.com/whatap/x.git")
    assert resolve_routing_account(repo, {"whatap": "heisgone"}) == ("heisgone", "mapping")


def test_resolve_account_unknown_plain_host_no_mapping(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "https://github.com/acme/x.git")
    assert resolve_routing_account(repo, {"whatap": "heisgone"}) == (None, "unknown")


def test_resolve_account_unknown_when_no_remote(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("")
    assert resolve_routing_account(tmp_path, {}) == (None, "unknown")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init.py -k resolve_account -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_routing_account'`

- [ ] **Step 3: 구현** — `src/anvyc/core/project_init.py` 끝에 추가

```python
def resolve_routing_account(
    path: Path, owner_accounts: dict[str, str]
) -> tuple[str | None, str]:
    """origin 으로부터 gh account 도출.

    1. origin ssh alias 있음 → (alias, "alias")  — `gh_route.resolve_account` 재사용
    2. alias 없음(plain host) → origin owner → `owner_accounts` 조회 → (account, "mapping")
    3. 도출 불가(remote 없음 / 매핑 없음) → (None, "unknown")
    """
    alias = gh_route.resolve_account(path)
    if alias:
        return (alias, "alias")
    for remote in parse_git_config(Path(path) / ".git"):
        if remote.name == "origin":
            mapped = owner_accounts.get(remote.owner)
            if mapped:
                return (mapped, "mapping")
            break
    return (None, "unknown")
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init.py -k resolve_account -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/project_init.py tests/unit/test_project_init.py
git commit -m "feat(project): resolve_routing_account — origin alias/owner 매핑 도출"
```

---

## Task 6: `gh_account_logged_in` — 로그인 검증(hosts.yml 존재)

**Files:**
- Modify: `src/anvyc/core/project_init.py`
- Test: `tests/unit/test_project_init.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/unit/test_project_init.py` 끝에 append

```python
from anvyc.core.project_init import gh_account_logged_in


def test_logged_in_true_when_hosts_yml_exists(tmp_path: Path) -> None:
    (tmp_path / "gh-16bitdo").mkdir()
    (tmp_path / "gh-16bitdo" / "hosts.yml").write_text("github.com: {}\n")
    assert gh_account_logged_in("16bitdo", config_home=tmp_path) is True


def test_logged_in_false_when_absent(tmp_path: Path) -> None:
    assert gh_account_logged_in("none", config_home=tmp_path) is False
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init.py -k logged_in -v`
Expected: FAIL — `ImportError: cannot import name 'gh_account_logged_in'`

- [ ] **Step 3: 구현** — `src/anvyc/core/project_init.py` 끝에 추가

```python
def gh_account_logged_in(account: str, config_home: Path | None = None) -> bool:
    """`<config_home>/gh-<account>/hosts.yml` 존재 여부 (= 해당 계정 로그인됨).

    `config_home` 기본 `$HOME/.config`. **내용은 보지 않고 존재만 stat** (토큰 미접근).
    """
    base = config_home or (Path.home() / ".config")
    return (base / f"gh-{account}" / "hosts.yml").is_file()
```

- [ ] **Step 4: 통과 확인 + 전체 단위 GREEN**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/project_init.py tests/unit/test_project_init.py
git commit -m "feat(project): gh_account_logged_in — hosts.yml 존재로 로그인 검증"
```

---

## Task 7: `project init` CLI 커맨드 + 통합 테스트

**Files:**
- Modify: `src/anvyc/cli.py` (`project_list` 함수 정의 끝 `:2274` 다음, `activity` 커맨드 `:2277` 앞)
- Test: `tests/unit/test_project_init_cli.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/test_project_init_cli.py` 신규

```python
"""anvyc project init CLI 동작 테스트 (CliRunner)."""
from __future__ import annotations

import textwrap
from pathlib import Path

from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def _repo_with_origin(tmp_path: Path, url: str) -> Path:
    g = tmp_path / ".git"
    g.mkdir(parents=True)
    (g / "config").write_text(textwrap.dedent(f"""\
        [remote "origin"]
            url = {url}
    """))
    return tmp_path


def test_init_alias_yes_writes_envrc_and_gitignore(tmp_path: Path) -> None:
    repo = _repo_with_origin(tmp_path, "git@github.com-16bitdo:16bitdo/x.git")
    result = runner.invoke(
        app, ["project", "init", "--path", str(repo), "--yes", "--no-allow"]
    )
    assert result.exit_code == 0, result.stdout
    assert (repo / ".envrc").read_text() == 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n'
    assert ".envrc" in (repo / ".gitignore").read_text()


def test_init_account_override(tmp_path: Path) -> None:
    repo = _repo_with_origin(tmp_path, "git@github.com-16bitdo:16bitdo/x.git")
    result = runner.invoke(
        app,
        ["project", "init", "--path", str(repo), "--account", "custom", "--yes", "--no-allow"],
    )
    assert result.exit_code == 0, result.stdout
    assert 'gh-custom' in (repo / ".envrc").read_text()


def test_init_no_git_errors_without_writing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["project", "init", "--path", str(tmp_path), "--yes"])
    assert result.exit_code == 1
    assert not (tmp_path / ".envrc").exists()


def test_init_yes_undederivable_errors(tmp_path: Path) -> None:
    repo = _repo_with_origin(tmp_path, "https://github.com/acme/x.git")
    result = runner.invoke(
        app, ["project", "init", "--path", str(repo), "--yes", "--no-allow"]
    )
    assert result.exit_code == 1
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init_cli.py -v`
Expected: FAIL — `No such command 'init'` (exit code 2)

- [ ] **Step 3: 커맨드 구현** — `src/anvyc/cli.py` `project_list` 끝(`:2274`) 다음에 추가

```python
@project_app.command("init")
def project_init(
    path: Path = typer.Option(Path.cwd(), "--path", help="대상 project root (default: cwd)."),
    account: str | None = typer.Option(
        None, "--account", "-a", help="gh account 직접 지정 (프롬프트 skip)."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="비대화 — 도출값/기본 동작 자동 수락."
    ),
    no_allow: bool = typer.Option(False, "--no-allow", help="direnv allow 실행 안 함."),
    config: Path | None = typer.Option(
        None, "--config", help="anvyc.yaml 경로 (owner→account 매핑)."
    ),
) -> None:
    """origin 기준 gh 계정 라우팅 `.envrc` 스캐폴딩 (project doctor #3 의 교정 측면)."""
    import shutil

    from anvyc.core.config import load_anvyc_config
    from anvyc.core.project_init import (
        ensure_gitignore_entry,
        gh_account_logged_in,
        resolve_routing_account,
        write_envrc_gh_routing,
    )

    root = path.resolve()
    if not (root / ".git").exists():
        console.print(f"[red]error[/] git repo 아님 (.git 없음): {root}")
        raise typer.Exit(code=1)

    if account:
        acct = account
    else:
        owner_accounts = load_anvyc_config(config).doctor.gh_owner_accounts
        derived, _source = resolve_routing_account(root, owner_accounts)
        if yes:
            if not derived:
                console.print(
                    "[red]error[/] origin 에서 gh 계정 도출 불가 — --account 로 지정하세요."
                )
                raise typer.Exit(code=1)
            acct = derived
        elif derived:
            acct = typer.prompt("gh account", default=derived)
        else:
            acct = typer.prompt("gh account (예: 16bitdo)")

    if not gh_account_logged_in(acct):
        console.print(
            f"[yellow]warning[/] 계정 '{acct}' 미인증 "
            f"(~/.config/gh-{acct}/hosts.yml 없음). "
            f"`GH_CONFIG_DIR=~/.config/gh-{acct} gh auth login -h github.com` 로 로그인 권장."
        )
        if not yes and not _confirm("그래도 .envrc 를 작성할까요?", default=True):
            raise typer.Exit(code=0)

    envrc_status = write_envrc_gh_routing(root / ".envrc", acct)
    gi_changed = ensure_gitignore_entry(root / ".gitignore", ".envrc")

    if no_allow:
        allow_msg = "direnv allow skip (--no-allow) — 수동: direnv allow"
    elif shutil.which("direnv"):
        subprocess.run(["direnv", "allow", str(root)])
        allow_msg = "direnv allow 완료"
    else:
        allow_msg = "direnv 미설치 — 설치 후 `direnv allow` 필요"

    console.print(f"[green]✓[/] .envrc GH_CONFIG_DIR → gh-{acct} ({envrc_status})")
    console.print(
        f"[green]✓[/] .gitignore .envrc 등록 ({'추가' if gi_changed else '이미 있음'})"
    )
    console.print(f"[green]✓[/] {allow_msg}")
    console.print(
        f"[dim]statusline 은 해당 디렉터리에서 다음 Claude Code 재시작 후 🔑 {acct} 로 전환[/]"
    )
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/unit/test_project_init_cli.py -v`
Expected: PASS (4 passed)
> 비고: `test_init_alias_yes...` 는 `gh_account_logged_in("16bitdo")` 가 실 머신의 `~/.config/gh-16bitdo/hosts.yml` 유무와 무관하게 `--yes` 라 경고만 찍고 진행 → .envrc 작성됨.

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/cli.py tests/unit/test_project_init_cli.py
git commit -m "feat(project): anvyc project init — gh 라우팅 .envrc 스캐폴딩 커맨드"
```

---

## Task 8: 채택(doctor 힌트) + 문서 + 전체 게이트

**Files:**
- Modify: `src/anvyc/core/project_doctor.py:134-137`(힌트 추가)
- Modify: `docs/multi-account.md`

- [ ] **Step 1: doctor 누락 suggestion 에 init 힌트 추가** — `project_doctor.py` 누락 케이스(Task 2 에서 고친 134-137 블록)

변경 후:
```python
                suggestion=(
                    f'.envrc 에 export GH_CONFIG_DIR="{gh_config_dir_for_account(alias)}" '
                    f"추가 후 direnv allow (또는 `anvyc project init`)"
                ),
```

- [ ] **Step 2: doctor 테스트 GREEN 확인 (부분문자열 assert 라 영향 없음)**

Run: `.venv/bin/python -m pytest tests/unit/test_project_gh_account.py tests/unit/test_project_doctor_render.py -v`
Expected: PASS
> 만약 어떤 테스트가 suggestion 을 **정확 일치**로 assert 해 실패하면, 그 테스트의 기대값을 위 새 문자열로 갱신(부분문자열 assert 면 변경 불필요).

- [ ] **Step 3: 문서 추가** — `docs/multi-account.md` 에 "신규 프로젝트 셋업" 섹션 추가 (파일 끝에 append)

```markdown

## 신규 프로젝트 gh 라우팅 셋업

owner 가 16bitdo/whatap 인 repo 를 새로 clone 하면 per-project `.envrc` 라우팅을 1회 명령으로 만든다:

```bash
cd ~/dev/<new-repo>
anvyc project init        # origin alias 에서 계정 도출 → 확인(Enter) → .envrc + .gitignore + direnv allow
```

- origin SSH alias(`github.com-<account>`)가 있으면 계정 자동 도출, 없으면 입력 요청.
- `--account <name>` 으로 직접 지정, `--yes` 로 비대화, `--no-allow` 로 direnv allow skip.
- `anvyc project doctor` #3(`gh_account_routing`)가 누락을 감지하면 이 명령으로 교정한다.
```

- [ ] **Step 4: 전체 게이트 — 테스트 + lint + 타입**

Run:
```bash
.venv/bin/python -m pytest tests/unit/test_project_init.py tests/unit/test_project_init_cli.py tests/unit/test_project_gh_account.py tests/unit/test_project_doctor_render.py -v
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
```
Expected: pytest PASS, ruff `All checks passed!`, mypy `Success` (또는 기존과 동일한 무관 경고만)

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/project_doctor.py docs/multi-account.md
git commit -m "feat(project): doctor #3 가 anvyc project init 힌트 + 문서"
```

---

## Self-Review

**1. Spec coverage** (spec §1–12 ↔ task):
- §3 인터페이스 `project init` → Task 7. 도출 재사용 → Task 5. 정적 리터럴 `.envrc` → Task 1·3. 멱등 replace → Task 3. 도출값 default 프롬프트 → Task 7.
- §5 컴포넌트: `gh_config_dir_for_account`(T1), `write_envrc_gh_routing`(T3), `ensure_gitignore_entry`(T4), `resolve_routing_account`(T5), `gh_account_logged_in`(T6), CLI(T7). 재사용 `gh_route.resolve_account`/`parse_git_config`(T5).
- §6 계정 결정 우선순위(explicit→alias→mapping→prompt) → T7 + T5. 가드(no-git/미인증/--yes) → T7.
- §7 보안(경로만 기록, hosts.yml 존재만) → T6, T7. §8 채택(doctor 힌트+문서) → T8. §9 테스트 → 각 Task TDD. §10 가법/롤백 → 순수 추가. §11 성공기준 → T8 게이트.
- §12 한계(statusline 즉시성) → 코드 변경 없음(문서화로 종결). **갭 없음.**

**2. Placeholder scan:** 모든 step 에 실제 코드/명령/기대출력 포함. TBD/TODO 없음.

**3. Type consistency:** `gh_config_dir_for_account(str)->str`, `write_envrc_gh_routing(Path,str)->str`, `ensure_gitignore_entry(Path,str)->bool`, `resolve_routing_account(Path,dict)->tuple[str|None,str]`, `gh_account_logged_in(str,Path|None)->bool` — T7 호출부 시그니처와 일치. `load_anvyc_config(config).doctor.gh_owner_accounts: dict[str,str]` 확인(config.py:118,206).

---

## Execution Handoff

(작성 후 별도 안내)
