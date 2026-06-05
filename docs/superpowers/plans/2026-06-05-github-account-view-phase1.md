# `anvyc github account` — GitHub 계정 통합 뷰 Phase 1 (읽기 전용) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 머신의 GitHub 계정 인벤토리(account/host/config_dir) + 로그인 여부 + (opt-in) 토큰 만료 + **현재 프로젝트 라우팅 해석**을 `anvyc github account list/show` 로 보고한다(읽기 전용; 기본 offline, 진짜 만료는 `--probe` opt-in). `aws profile list/show` 의 GitHub 대응물.

**Architecture:** 순수 오프라인 조립 코어 `core/gh_account_view.py`(네트워크 0)가 기존 secret-safe 프리미티브를 합성한다 — 인벤토리 `utils/gh_hosts.discover_gh_accounts`(`~/.config/gh*` walk, host/user 만), 로그인 stat, owner→account 역인덱스(`config.gh_owner_accounts`), cwd 라우팅 `gh_route.resolve_account`. 네트워크 만료 probe 는 `core/gh_probe.py` 로 **물리적 분리**(aws 의 `aws_profile_state.py`+`aws_probe.py` 미러) — CLI 의 `--probe` 경로에서만 import 해 view 코어가 구조적으로 offline 임을 보장. 명령 표면은 신규 `github` 그룹(`anvyc gh` passthrough 와 분리).

**Tech Stack:** Python 3.13, Typer(CLI), `pytest`+`typer.testing.CliRunner`, `subprocess`(probe).

**Spec:** `docs/superpowers/specs/2026-06-05-anvyc-github-account-and-routing-design.md` (§4 아키텍처, §5 뷰 모델, §6.1 조회, §9 Phase 1; 결정 §3·§12).

**구현 정밀화 메모(spec 대비)**:
- **`detect_github` 미사용** — spec §4 는 만료에 `core/creds.py:detect_github(probe_expiry=True)` 재사용을 언급하나, `detect_github` 은 `~/.config/gh/hosts.yml`(**기본 dir 만**) 하드코딩이라 anvyc 의 per-account dir(`~/.config/gh-<acct>`)을 못 본다. → Phase 1 은 인벤토리를 `discover_gh_accounts`(전 dir walk)에서 얻고, 만료는 **per-dir** `core/gh_probe.probe_token_expiry(config_dir, host, user)`(`GH_CONFIG_DIR=<dir> gh api` 헤더)로 본다. `cost/adapters/github.py` 의 `GH_CONFIG_DIR=<dir> gh ...` 패턴 선례.
- **로그인 판정 = 발견 멤버십** — `discover_gh_accounts` 가 곧 hosts.yml 에 존재(=로그인)한 계정 집합. 별도 `gh_account_logged_in` 호출 불필요. "미로그인"은 **매핑(owner_accounts)에는 있으나 발견 집합에 없는** account 로만 발생(spec §5 마지막 행).
- **host 가정** — 매핑-only(미발견) account 는 host 미상이라 `github.com` 으로 가정 표기(routing 매핑은 host 를 안 담음). 발견된 account 는 실제 host 사용.
- **토큰 불가침 단언** — view 코어 테스트는 hosts.yml 에 `oauth_token` 라인을 넣고도 결과·로그 어디에도 그 값이 없음을 단언(회귀 가드).
- spec §6 의 `--aws-config` 류 경로 override 없음 — 테스트는 `config_home`/`HOME` monkeypatch 로 격리(aws Phase 1 컨벤션 동일).

---

## File Structure

**신규 파일**
- `src/anvyc/core/gh_account_view.py` — `@dataclass GhAccountView`, `collect_accounts(*, config_home, owner_accounts, cwd, probe_results=None) -> list[GhAccountView]`. **네트워크 의존 0.**
- `src/anvyc/core/gh_probe.py` — `@dataclass GhProbeResult`, `probe_token_expiry(config_dir, host, user, *, timeout=8.0) -> GhProbeResult`. `--probe` 전용(네트워크).
- `tests/unit/test_gh_account_view.py`, `tests/unit/test_gh_probe.py`, `tests/unit/test_github_cli.py`

**수정 파일**
- `src/anvyc/cli.py` — `github_app`/`github_account_app` 등록 + `account list`/`show`.
- `README.md`, `docs/multi-account.md` — `anvyc github account` 사용 예.

**시그니처**
```
# core/gh_account_view.py
@dataclass(frozen=True)
class GhAccountView:
    account: str; host: str; config_dir: str | None
    logged_in: bool; expiry_status: str; expires_at: str | None
    routed_owners: list[str]; cwd_routed: bool
collect_accounts(*, config_home: Path | None, owner_accounts: dict[str, str],
                 cwd: Path, probe_results: dict[tuple[str, str], "GhProbeResult"] | None = None) -> list[GhAccountView]
# core/gh_probe.py
@dataclass(frozen=True)
class GhProbeResult: status: str; expires_at: str | None
probe_token_expiry(config_dir: Path, host: str, user: str, *, timeout: float = 8.0) -> GhProbeResult
```
`expiry_status`: `valid|expiring|expired|unknown`(probe 시) / `unknown`(offline 기본).

---

## Task 1: `core/gh_account_view.collect_accounts` — 오프라인 조립 (네트워크 0)

**Files:**
- Create: `src/anvyc/core/gh_account_view.py`
- Test: `tests/unit/test_gh_account_view.py`

- [ ] **Step 1: Write the failing test**

```python
"""core/gh_account_view — 오프라인 계정 뷰 조립(네트워크 0)."""
from pathlib import Path

from anvyc.core.gh_account_view import collect_accounts


def _mk_gh(config_home: Path, dirname: str, host: str, user: str) -> None:
    d = config_home / dirname
    d.mkdir(parents=True, exist_ok=True)
    # oauth_token 라인 포함 — 토큰 불가침 회귀 가드
    (d / "hosts.yml").write_text(
        f"{host}:\n    users:\n        {user}:\n            oauth_token: ghp_SECRET_DO_NOT_READ\n",
        encoding="utf-8",
    )


def test_discovered_account_logged_in(tmp_path: Path) -> None:
    ch = tmp_path / ".config"
    _mk_gh(ch, "gh-16bitdo", "github.com", "16bitdo")
    views = collect_accounts(config_home=ch, owner_accounts={}, cwd=tmp_path)
    assert len(views) == 1
    v = views[0]
    assert v.account == "16bitdo" and v.logged_in is True
    assert v.config_dir is not None and v.expiry_status == "unknown"


def test_routed_owners_reverse_index(tmp_path: Path) -> None:
    ch = tmp_path / ".config"
    _mk_gh(ch, "gh-heisgone", "github.com", "heisgone")
    views = collect_accounts(
        config_home=ch, owner_accounts={"whatap": "heisgone"}, cwd=tmp_path
    )
    assert views[0].routed_owners == ["whatap"]


def test_mapped_but_not_logged_in(tmp_path: Path) -> None:
    ch = tmp_path / ".config"
    ch.mkdir(parents=True)
    views = collect_accounts(
        config_home=ch, owner_accounts={"acme": "ghost"}, cwd=tmp_path
    )
    ghost = next(v for v in views if v.account == "ghost")
    assert ghost.logged_in is False and ghost.config_dir is None


def test_no_token_value_leaks(tmp_path: Path) -> None:
    ch = tmp_path / ".config"
    _mk_gh(ch, "gh-16bitdo", "github.com", "16bitdo")
    views = collect_accounts(config_home=ch, owner_accounts={}, cwd=tmp_path)
    assert "ghp_SECRET_DO_NOT_READ" not in repr(views)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_gh_account_view.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'anvyc.core.gh_account_view'`.

- [ ] **Step 3: Add the implementation**

`src/anvyc/core/gh_account_view.py` 신규: `discover_gh_accounts(config_home)` 로 인벤토리(=logged_in) 수집 → 각 account 의 `routed_owners`(owner_accounts 역인덱스)·`cwd_routed`(`gh_route.resolve_account(cwd)==account`) 계산. owner_accounts 값 중 미발견 account 는 `logged_in=False, config_dir=None` 으로 추가. `probe_results` 가 주어지면 `(host,user)` 키로 `expiry_status`/`expires_at` 병합, 아니면 `"unknown"`. **`gh_probe` import 안 함**(네트워크 0).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_gh_account_view.py -v` → PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/gh_account_view.py tests/unit/test_gh_account_view.py
git commit -m "feat(github): gh_account_view.collect_accounts — 오프라인 계정 뷰 조립"
```

---

## Task 2: `core/gh_probe.probe_token_expiry` — per-dir 만료 probe (`--probe` 전용)

**Files:**
- Create: `src/anvyc/core/gh_probe.py`
- Test: `tests/unit/test_gh_probe.py`

- [ ] **Step 1: Write the failing test** — `subprocess.run` monkeypatch 로 `X-GitHub-Token-Expiration` 헤더 있는 응답/없는 응답/`gh` 부재(`FileNotFoundError`)/timeout 케이스. 각각 `valid`(또는 분류)/`unknown`/`unknown` 반환 + `GH_CONFIG_DIR` 가 child env 에 설정되는지 + 토큰 미출력 단언.

- [ ] **Step 2: Run test to verify it fails** — `ModuleNotFoundError: anvyc.core.gh_probe`.

- [ ] **Step 3: Add the implementation** — `GH_CONFIG_DIR=<config_dir>` env 로 `gh api -i user --hostname <host>` subprocess(timeout). stdout 헤더에서 `X-GitHub-Token-Expiration` 파싱 → `core/creds._classify` 동등 로직으로 `valid|expiring|expired`, 헤더 부재 → `unknown`. `gh` 부재/실패/timeout → `GhProbeResult("unknown", None)`(graceful). 토큰은 어디에도 출력 안 함.

- [ ] **Step 4: Run test to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/gh_probe.py tests/unit/test_gh_probe.py
git commit -m "feat(github): gh_probe.probe_token_expiry — per-dir 토큰 만료 probe (opt-in)"
```

---

## Task 3: CLI `anvyc github account list`

**Files:**
- Modify: `src/anvyc/cli.py`
- Test: `tests/unit/test_github_cli.py`

- [ ] **Step 1: Write the failing test** — `CliRunner`: tmp `config_home`(HOME monkeypatch) 에 계정 2개 구성 → `github account list` 가 account 명·로그인·라우팅 노출(`--json` 은 §6.1 스키마). `--probe` 시 `gh_probe.probe_token_expiry` monkeypatch 결과가 `expiry_status` 에 반영. `--probe` 미지정 시 probe **미호출**(네트워크 0) 단언. 토큰 미출력 단언.

- [ ] **Step 2: Run test to verify it fails** — `No such command 'github'`.

- [ ] **Step 3: Add the implementation** — `cli.py` 에 `github_app = _typer(name="github", help="GitHub 계정 통합 뷰/라우팅 (~/.config/gh*).")` + `app.add_typer(github_app, name="github", rich_help_panel=PANEL_PROJECT)`; `github_account_app = _typer(name="account", ...)` + `github_app.add_typer(.., "account")`. `account list(--json, --probe)`: `--probe` 시 발견 account 별 `probe_token_expiry` 호출해 `probe_results` 구성 → `collect_accounts(..., probe_results=...)` → 테이블/JSON. 출력 규약 doctor 동일(Panel 미사용, `escape`).

- [ ] **Step 4: Run test to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_github_cli.py
git commit -m "feat(github): anvyc github account list — 계정 통합 뷰 (--probe/--json)"
```

---

## Task 4: CLI `anvyc github account show <account>`

**Files:**
- Modify: `src/anvyc/cli.py`
- Test: `tests/unit/test_github_cli.py`

- [ ] **Step 1: Write the failing test** — `github account show 16bitdo` 가 host·config_dir·로그인·만료·이 계정 라우팅 owners·cwd 여부 출력. 미존재 account → 명확 메시지 + 비0 exit. `--json` 단일 객체. `--probe` 반영.

- [ ] **Step 2: Run test to verify it fails** — `No such command 'show'`.

- [ ] **Step 3: Add the implementation** — `account show(name, --json, --probe)`: `collect_accounts` 결과에서 `account==name` 선택(없으면 exit 1 + 안내). `--probe` 시 해당 account 만 probe.

- [ ] **Step 4: Run test to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_github_cli.py
git commit -m "feat(github): anvyc github account show — 단일 계정 상세"
```

---

## Task 5: 문서 + 회귀 가드

**Files:**
- Modify: `README.md`, `docs/multi-account.md`, `DESIGN.md`
- Test: 기존 스위트

- [ ] **Step 1**: `README.md` §11 GitHub 행에 `anvyc github account list/show [--probe]` 추가(인증은 `gh auth` 위임 명기). `docs/multi-account.md`·`DESIGN.md` 갱신.
- [ ] **Step 2: 회귀 가드 실행** — `pytest -q` 전체 GREEN. 특히 `anvyc gh <args>` passthrough(`test_*gh*`)·`creds status` GitHub·`project doctor gh_account_routing` 불변 확인.
- [ ] **Step 3: lint/type** — `.venv/bin/ruff check src tests && .venv/bin/mypy src/anvyc/cli.py src/anvyc/core/gh_account_view.py src/anvyc/core/gh_probe.py`.
- [ ] **Step 4: Commit**

```bash
git add README.md docs/multi-account.md DESIGN.md
git commit -m "docs(github): anvyc github account 사용 예 + 인증 위임 경계"
```

---

## 완료 기준 (Phase 1)

- `anvyc github account list` 가 발견 계정 + 로그인 + 라우팅(owners/✓cwd)을, `--probe` 시 만료까지 보고.
- `github account show <account>` 단일 상세 + 미존재 비0 exit.
- view 코어 **네트워크 0**(probe 미import), 토큰 값 미노출(테스트 단언).
- `anvyc gh` passthrough·`creds`·`project doctor` 회귀 0. `ruff`/`mypy` GREEN.
- 다음(별도 PR): **Phase 2** — `github route list/set/rm`(anvyc.yaml 안전쓰기) + `github use`(.envrc).
