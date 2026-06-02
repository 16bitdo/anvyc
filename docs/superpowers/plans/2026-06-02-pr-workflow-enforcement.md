# PR-기반 워크플로 강제 — 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 16bitdo 16개 repo 에서 main 직접 push 를 막고 PR→머지 경로를 강제한다(manifest SoT + 로컬 hook + 서버 ruleset + doctor drift 관측).

**Architecture:** 정책은 role-based-ruleset 의 `branch-strategies.yaml` 한 곳에서 정의(SoT). anvyc 가 이를 subprocess(`lookup_branch_strategy.py`)로 읽어 ① 로컬 `.git/hooks/pre-push` 가드를 설치하고 ② GitHub repository ruleset 으로 변환·적용하며 ③ doctor check 로 3자 정합을 관측한다.

**Tech Stack:** Python 3.11+(StrEnum), typer(CLI), pytest, `gh` CLI(repository rulesets API), bash(pre-push hook).

**설계 문서:** `docs/superpowers/specs/2026-06-01-pr-workflow-enforcement-design.md`

**대상 16개:** aiforge, analysis, anvyc, anvyc-internal, anvyx, api-test-hub, architecture, ccinspector, ctxport, cursor-ide, dotfiles-claude, homebrew-anvyc, pulumi-dev, rca, role-based-ruleset, security-scan.

---

## 파일 구조 (생성/수정 맵)

**role-based-ruleset 저장소 (Phase 1 — 별도 브랜치/PR):**
- Modify: `metadata/branch-strategies.yaml` — 16bitdo 16개 entry 정책 전환 + stale 주석 정정

**anvyc 저장소 (Phase 2~5 — 브랜치 `feat/pr-workflow-enforcement`):**
- Create: `src/anvyc/core/branch_policy.py` — `BranchPolicy` + `resolve_policy()` (ruleset lookup subprocess + 안전 fallback)
- Create: `src/anvyc/core/git_guards.py` — pre-push 가드 렌더링 + hooks-dir 해소 + `install_pre_push_guard()`
- Create: `src/anvyc/core/git_protect.py` — ruleset payload + `gh api` 래퍼 + `get_ruleset()`/`apply_ruleset()`
- Create: `src/anvyc/checks/project_branch_protection.py` — L3 doctor check
- Modify: `src/anvyc/core/doctor.py:50-73` — `_REGISTRY` 에 check 등록
- Modify: `src/anvyc/cli.py:105-172` 근처 — `guard_app` sub-app + `install`/`protect` 커맨드 (`git` sub-app 은 .anvyc 전용이라 신규 `guard` 그룹 사용)
- Create 테스트: `tests/unit/test_branch_policy.py`, `tests/unit/test_git_guards.py`, `tests/unit/test_git_protect.py`, `tests/unit/test_project_branch_protection.py`, `tests/integration/test_guard_cli.py`
- Modify: `DESIGN.md` — 신규 control-plane 항목, `docs/superpowers/specs/...` 상태 갱신

각 모듈은 책임 단일: `branch_policy`=정책 해소, `git_guards`=로컬 hook, `git_protect`=서버 ruleset, check=관측. 외부 호출(subprocess/gh/fs)은 전부 모듈 레벨 함수로 분리해 테스트에서 patch 가능하게 한다.

---

## Phase 1 — manifest 정책 전환 (role-based-ruleset, spec L0)

> 이 Phase 는 **role-based-ruleset 저장소**에서 수행한다. anvyc 브랜치와 무관.

### Task 1.1: 작업 브랜치 cut + manifest 16개 entry 전환

**Files:**
- Modify: `~/dev/role-based-ruleset/metadata/branch-strategies.yaml`

- [ ] **Step 1: 브랜치 cut**

```bash
cd ~/dev/role-based-ruleset
git switch -c chore/branch-strategy-16bitdo-pr-required
```

- [ ] **Step 2: 16bitdo 16개 entry 를 defaults 상속 + `pr_reviewers_min: 0` 으로 정규화**

각 16bitdo entry 에서 `push_to_main_allowed: true` / `pr_required: false` override 라인을 **삭제**하면
defaults(`push_to_main_allowed:false, pr_required:true, merge_strategy:squash, protected_branches:[main]`)를
상속한다. 거기에 `pr_reviewers_min: 0` 만 명시(개인 repo 는 본인 PR self-approve 불가 → 0 이어야 머지 가능).

예시 — `aiforge` (다른 15개도 동일 패턴; `role-based-ruleset` 은 이미 false/true 라 `pr_reviewers_min: 0` 만 추가):

```yaml
  - id: aiforge
    path: ~/dev/aiforge
    remote: github.com:16bitdo/aiforge
    pr_reviewers_min: 0
```

대상 16개 id: `aiforge, analysis, anvyc, anvyc-internal, anvyx, api-test-hub, architecture, ccinspector, ctxport, cursor-ide, dotfiles-claude, homebrew-anvyc, pulumi-dev, rca, role-based-ruleset, security-scan`.
(manifest 에 `anvyc-internal`·`cursor-ide` 등 누락분이 있으면 동일 형식으로 추가: `id`/`path`/`remote`/`pr_reviewers_min: 0`.)

- [ ] **Step 3: stale 주석 정정**

`metadata/branch-strategies.yaml:39` 의

```yaml
  # ── 16bitdo (개인 free 계정, branch protection 미지원 → main push 허용) ──
```

를 검증된 사실로 교체:

```yaml
  # ── 16bitdo (개인 계정) — repository ruleset 지원 확인(2026-06-01). PR 필수, self-merge(min=0). ──
```

- [ ] **Step 4: 스키마 검증 (실패 없어야 함)**

Run: `python3 scripts/validate_branch_strategies.py`
Expected: `OK: N project(s), M warning(s)` (exit 0)

- [ ] **Step 5: lookup 회귀 + 정책 반영 확인**

Run:
```bash
bash scripts/test_lookup_branch_strategy.sh
python3 scripts/lookup_branch_strategy.py --cwd ~/dev/aiforge --format json
```
Expected: 회귀 통과(exit 0). aiforge json 에 `"push_to_main_allowed": false, "pr_required": true, "pr_reviewers_min": 0`.

- [ ] **Step 6: 커밋**

```bash
git add metadata/branch-strategies.yaml
git commit -m "chore(branch-strategy): 16bitdo 16개 repo PR 필수 전환(self-merge min=0)

repository ruleset 지원 확인으로 stale 'free=protection불가' 가정 정정.
defaults(push_to_main_allowed=false, pr_required=true) 상속 + pr_reviewers_min=0."
```

### Task 1.2: CLAUDE.md 전파 + PR

- [ ] **Step 1: 영향 받는 프로젝트 CLAUDE.md DRY-RUN**

Run: `python3 scripts/generate_claude_md.py`
Expected: 정책 컨텍스트 변경분 diff 미리보기(에러 없음).

- [ ] **Step 2: 반영**

Run: `python3 scripts/generate_claude_md.py --apply`
Expected: generated marker 있는 CLAUDE.md 갱신.

- [ ] **Step 3: PR 생성(자기 dogfooding — role-based-ruleset 도 이제 PR 필수)**

```bash
git push -u origin chore/branch-strategy-16bitdo-pr-required
gh pr create --fill --base main
```
Expected: PR URL 출력. (이후 본인 머지 — squash.)

---

## Phase 2 — 정책 해소 + 로컬 가드 (anvyc, spec L1)

### Task 2.1: `branch_policy` 모듈 — ruleset lookup 으로 정책 해소

**Files:**
- Create: `src/anvyc/core/branch_policy.py`
- Test: `tests/unit/test_branch_policy.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/unit/test_branch_policy.py
"""Unit tests for anvyc.core.branch_policy."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from anvyc.core.branch_policy import (
    FALLBACK_POLICY,
    BranchPolicy,
    resolve_policy,
)


def _fake_proc(stdout: str, rc: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["x"], returncode=rc, stdout=stdout, stderr="")


def test_resolve_policy_parses_manifest_json(tmp_path: Path) -> None:
    payload = {
        "registered": True,
        "policy": {
            "default_branch": "main",
            "protected_branches": ["main"],
            "push_to_main_allowed": False,
            "pr_required": True,
            "pr_reviewers_min": 0,
            "merge_strategy": "squash",
        },
    }
    with patch("anvyc.core.branch_policy.find_lookup_script", return_value=tmp_path / "s.py"), \
         patch("anvyc.core.branch_policy.subprocess.run", return_value=_fake_proc(json.dumps(payload))):
        pol = resolve_policy(tmp_path)
    assert isinstance(pol, BranchPolicy)
    assert pol.push_to_main_allowed is False
    assert pol.pr_reviewers_min == 0
    assert pol.protected_branches == ("main",)
    assert pol.source == "manifest"


def test_resolve_policy_fallback_when_no_script(tmp_path: Path) -> None:
    with patch("anvyc.core.branch_policy.find_lookup_script", return_value=None):
        pol = resolve_policy(tmp_path)
    assert pol == FALLBACK_POLICY
    assert pol.push_to_main_allowed is False  # 안전 기본값
    assert pol.source == "fallback"


def test_resolve_policy_fallback_on_bad_json(tmp_path: Path) -> None:
    with patch("anvyc.core.branch_policy.find_lookup_script", return_value=tmp_path / "s.py"), \
         patch("anvyc.core.branch_policy.subprocess.run", return_value=_fake_proc("not json")):
        pol = resolve_policy(tmp_path)
    assert pol.source == "fallback"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_branch_policy.py -v`
Expected: FAIL — `ModuleNotFoundError: anvyc.core.branch_policy`

- [ ] **Step 3: 최소 구현**

```python
# src/anvyc/core/branch_policy.py
"""branch-strategies.yaml(role-based-ruleset) 정책을 해소한다.

SoT 는 role-based-ruleset. anvyc 는 그 `scripts/lookup_branch_strategy.py` 를
subprocess 로 호출(--format json)해 정책을 읽고, 스크립트/매니페스트가 없으면
안전 fallback(push_to_main_allowed=false)을 쓴다. DESIGN.md 신규 CP 참고.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

RULESET_DIR_ENV = "ANVYC_RULESET_DIR"
DEFAULT_RULESET_DIR = Path("~/dev/role-based-ruleset")


@dataclass(frozen=True)
class BranchPolicy:
    default_branch: str
    protected_branches: tuple[str, ...]
    push_to_main_allowed: bool
    pr_required: bool
    pr_reviewers_min: int
    merge_strategy: str
    source: str  # "manifest" | "defaults" | "fallback"


FALLBACK_POLICY = BranchPolicy(
    default_branch="main",
    protected_branches=("main",),
    push_to_main_allowed=False,
    pr_required=True,
    pr_reviewers_min=0,
    merge_strategy="squash",
    source="fallback",
)


def find_lookup_script() -> Path | None:
    base = os.environ.get(RULESET_DIR_ENV)
    root = Path(base).expanduser() if base else DEFAULT_RULESET_DIR.expanduser()
    script = root / "scripts" / "lookup_branch_strategy.py"
    return script if script.is_file() else None


def resolve_policy(repo_dir: Path) -> BranchPolicy:
    """repo_dir 의 branch 정책을 ruleset lookup 으로 해소. 실패 시 FALLBACK_POLICY."""
    script = find_lookup_script()
    if script is None:
        return FALLBACK_POLICY
    try:
        proc = subprocess.run(
            ["python3", str(script), "--cwd", str(repo_dir), "--format", "json"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return FALLBACK_POLICY
    # exit 0=matched, 3=defaults(둘 다 json 출력); 그 외/빈출력 → fallback
    if proc.returncode not in (0, 3) or not proc.stdout.strip():
        return FALLBACK_POLICY
    try:
        data = json.loads(proc.stdout)
        pol = data["policy"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return FALLBACK_POLICY
    return BranchPolicy(
        default_branch=str(pol.get("default_branch", "main")),
        protected_branches=tuple(pol.get("protected_branches") or ["main"]),
        push_to_main_allowed=bool(pol.get("push_to_main_allowed", False)),
        pr_required=bool(pol.get("pr_required", True)),
        pr_reviewers_min=int(pol.get("pr_reviewers_min", 0)),
        merge_strategy=str(pol.get("merge_strategy", "squash")),
        source="manifest" if data.get("registered") else "defaults",
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_branch_policy.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/branch_policy.py tests/unit/test_branch_policy.py
git commit -m "feat(guard): branch_policy — ruleset lookup 으로 정책 해소 + 안전 fallback"
```

### Task 2.2: `git_guards` 모듈 — pre-push 가드 렌더/설치

**Files:**
- Create: `src/anvyc/core/git_guards.py`
- Test: `tests/unit/test_git_guards.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/unit/test_git_guards.py
"""Unit tests for anvyc.core.git_guards."""
from __future__ import annotations

import subprocess
from pathlib import Path

from anvyc.core.branch_policy import BranchPolicy
from anvyc.core.git_guards import (
    GUARD_BEGIN,
    GUARD_END,
    install_pre_push_guard,
    render_guard_block,
)

_POLICY = BranchPolicy(
    default_branch="main", protected_branches=("main",),
    push_to_main_allowed=False, pr_required=True, pr_reviewers_min=0,
    merge_strategy="squash", source="manifest",
)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    return path


def test_render_block_has_markers_and_guard() -> None:
    block = render_guard_block(_POLICY)
    assert GUARD_BEGIN in block and GUARD_END in block
    assert '__anvyc_allowed="false"' in block
    assert "refs/heads/$_b" in block


def test_install_fresh_creates_executable_hook(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    res = install_pre_push_guard(repo, _POLICY)
    hook = repo / ".git" / "hooks" / "pre-push"
    assert res.status == "installed"
    assert hook.is_file()
    assert hook.stat().st_mode & 0o111  # executable
    assert GUARD_BEGIN in hook.read_text()


def test_install_idempotent_updates_block(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    install_pre_push_guard(repo, _POLICY)
    res2 = install_pre_push_guard(repo, _POLICY)
    hook = repo / ".git" / "hooks" / "pre-push"
    assert res2.status == "updated"
    assert hook.read_text().count(GUARD_BEGIN) == 1  # 중복 없음


def test_install_skips_foreign_hook(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho mine\n")
    res = install_pre_push_guard(repo, _POLICY)
    assert res.status == "skipped-foreign"
    assert "echo mine" in hook.read_text()  # 보존


def test_install_force_backs_up_foreign(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho mine\n")
    res = install_pre_push_guard(repo, _POLICY, force=True)
    assert res.status == "installed"
    assert (repo / ".git" / "hooks" / "pre-push.pre-anvyc").read_text() == "#!/bin/sh\necho mine\n"
    assert GUARD_BEGIN in hook.read_text()


def test_install_skips_tracked_hookspath(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    (repo / "scripts" / "hooks").mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", "scripts/hooks"], check=True)
    res = install_pre_push_guard(repo, _POLICY)
    assert res.status == "skipped-tracked-hooks"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_git_guards.py -v`
Expected: FAIL — `ModuleNotFoundError: anvyc.core.git_guards`

- [ ] **Step 3: 최소 구현**

```python
# src/anvyc/core/git_guards.py
"""로컬 pre-push 가드 — 보호 브랜치 직접 push 를 차단한다.

`anvyc guard install` 이 대상 repo 의 effective hooks dir 에 marker 블록을 설치한다.
정책 스냅샷(protected/allowed)을 hook 에 임베드 → push 시점에 ruleset repo 의존 없음.
core.hooksPath 가 worktree 내부(tracked)면 clobber 금지하고 skip 한다.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from anvyc.core.branch_policy import BranchPolicy

GUARD_BEGIN = "# >>> anvyc-pr-guard >>>"
GUARD_END = "# <<< anvyc-pr-guard <<<"
_SHEBANG = "#!/usr/bin/env bash\nset -euo pipefail\n"


def render_guard_block(policy: BranchPolicy) -> str:
    protected = " ".join(policy.protected_branches)
    allowed = "true" if policy.push_to_main_allowed else "false"
    return (
        f"{GUARD_BEGIN}\n"
        f"# auto-generated; managed by `anvyc guard install`. policy_source={policy.source}\n"
        f'__anvyc_protected="{protected}"\n'
        f'__anvyc_allowed="{allowed}"\n'
        'if [ "$__anvyc_allowed" != "true" ]; then\n'
        "  while read -r _lref _lsha _rref _rsha; do\n"
        "    for _b in $__anvyc_protected; do\n"
        '      if [ "$_rref" = "refs/heads/$_b" ]; then\n'
        '        echo "" >&2\n'
        "        echo \"anvyc guard: '$_b' 직접 push 차단 (push_to_main_allowed=false).\" >&2\n"
        '        echo "  작업 브랜치 + PR 로 진행하세요:" >&2\n'
        '        echo "    git switch -c feat/<topic> && git push -u origin feat/<topic> && gh pr create --fill" >&2\n'
        "        exit 1\n"
        "      fi\n"
        "    done\n"
        "  done\n"
        "fi\n"
        f"{GUARD_END}\n"
    )


def effective_hooks_dir(repo_dir: Path) -> tuple[Path, bool]:
    """(hooks_dir, tracked_in_worktree) 반환. core.hooksPath 존중."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "config", "--get", "core.hooksPath"],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return repo_dir / ".git" / "hooks", False
    hp = proc.stdout.strip()
    if not hp:
        return repo_dir / ".git" / "hooks", False
    hooks = Path(hp) if Path(hp).is_absolute() else (repo_dir / hp)
    try:
        rel = hooks.resolve().relative_to(repo_dir.resolve())
        tracked = rel.parts[:1] != (".git",)
    except (ValueError, OSError):
        tracked = False
    return hooks, tracked


@dataclass
class GuardInstallResult:
    repo: Path
    status: str  # installed | updated | skipped-foreign | skipped-tracked-hooks
    detail: str = ""


def install_pre_push_guard(
    repo_dir: Path, policy: BranchPolicy, *, force: bool = False
) -> GuardInstallResult:
    hooks_dir, tracked = effective_hooks_dir(repo_dir)
    if tracked:
        return GuardInstallResult(repo_dir, "skipped-tracked-hooks", str(hooks_dir))
    hook = hooks_dir / "pre-push"
    block = render_guard_block(policy)
    if not hook.exists():
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook.write_text(_SHEBANG + block)
        hook.chmod(0o755)
        return GuardInstallResult(repo_dir, "installed")
    text = hook.read_text()
    if GUARD_BEGIN in text:
        pre = text.split(GUARD_BEGIN)[0]
        post = text.split(GUARD_END, 1)[1] if GUARD_END in text else "\n"
        hook.write_text(pre + block + post)
        hook.chmod(0o755)
        return GuardInstallResult(repo_dir, "updated")
    if not force:
        return GuardInstallResult(repo_dir, "skipped-foreign", str(hook))
    (hooks_dir / "pre-push.pre-anvyc").write_text(text)
    hook.write_text(_SHEBANG + block)
    hook.chmod(0o755)
    return GuardInstallResult(repo_dir, "installed", "backup=pre-push.pre-anvyc")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_git_guards.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/git_guards.py tests/unit/test_git_guards.py
git commit -m "feat(guard): git_guards — pre-push 가드 렌더/설치(marker·foreign 보존·hooksPath 존중)"
```

### Task 2.3: `anvyc guard install` CLI 커맨드

**Files:**
- Modify: `src/anvyc/cli.py` (sub-app 정의는 `cli.py:105-172` 블록, 커맨드는 그 아래)
- Test: `tests/integration/test_guard_cli.py`

- [ ] **Step 1: 실패하는 통합 테스트 작성**

```python
# tests/integration/test_guard_cli.py
"""anvyc guard CLI 통합 테스트."""
from __future__ import annotations

import subprocess
from pathlib import Path

from tests.integration._helpers import run_anvyc


def _git_repo_with_origin(path: Path, remote: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True)
    return path


def test_guard_install_dry_run_lists_targets(tmp_path: Path) -> None:
    repo = _git_repo_with_origin(tmp_path / "proj", "git@github.com:16bitdo/proj.git")
    proc = run_anvyc("guard", "install", "--project", str(repo), "--dry-run", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "proj" in proc.stdout
    assert not (repo / ".git" / "hooks" / "pre-push").exists()  # dry-run: 미설치


def test_guard_install_writes_hook(tmp_path: Path) -> None:
    repo = _git_repo_with_origin(tmp_path / "proj", "git@github.com:16bitdo/proj.git")
    proc = run_anvyc("guard", "install", "--project", str(repo), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    hook = repo / ".git" / "hooks" / "pre-push"
    assert hook.is_file()
    assert "anvyc-pr-guard" in hook.read_text()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/integration/test_guard_cli.py -v`
Expected: FAIL — `No such command 'guard'` (returncode != 0)

- [ ] **Step 3: sub-app + 커맨드 구현**

`cli.py` 의 sub-app 등록 블록(`cli.py:105-172` 인근)에 추가:

```python
guard_app = typer.Typer(
    name="guard",
    help="~/dev 프로젝트 branch 정책 강제 — 로컬 pre-push hook 설치 / 서버 ruleset 적용.",
)
app.add_typer(guard_app, name="guard", rich_help_panel=PANEL_CONTROL)
```

`install` 커맨드(파일 하단 커맨드 영역, 다른 `@app.command` 들과 같은 구역):

```python
@guard_app.command("install")
def guard_install(
    project: list[Path] | None = typer.Option(
        None, "--project", help="대상 repo 경로 (반복 가능). 생략 시 등록된 roots 전체."
    ),
    root: Path | None = typer.Option(None, "--root", help="스캔할 상위 디렉터리 (기본: 등록 roots)."),
    force: bool = typer.Option(False, "--force", help="기존 비-anvyc pre-push 를 백업하고 덮어쓴다."),
    dry_run: bool = typer.Option(False, "--dry-run", help="설치하지 않고 대상/정책만 출력."),
) -> None:
    """대상 repo 에 pre-push 가드(보호 브랜치 직접 push 차단)를 설치한다."""
    from anvyc.core.branch_policy import resolve_policy
    from anvyc.core.git_guards import install_pre_push_guard
    from anvyc.core.guard_targets import resolve_guard_targets

    targets = resolve_guard_targets(project, root)
    if not targets:
        console.print("[yellow]대상 repo 없음[/] (등록 roots/--project 확인)")
        raise typer.Exit(code=0)

    for repo in targets:
        policy = resolve_policy(repo)
        if dry_run:
            console.print(
                f"[dim]would install[/] {_short_path(repo)} "
                f"(protected={list(policy.protected_branches)}, "
                f"allow_main={policy.push_to_main_allowed}, src={policy.source})"
            )
            continue
        res = install_pre_push_guard(repo, policy, force=force)
        color = {"installed": "green", "updated": "green"}.get(res.status, "yellow")
        console.print(f"[{color}]{res.status}[/] {_short_path(repo)} {res.detail}")
```

- [ ] **Step 4: 대상 해소 헬퍼 작성**

```python
# src/anvyc/core/guard_targets.py
"""guard 대상 repo 해소 — --project / --root / 등록 roots 에서 .git repo 수집."""
from __future__ import annotations

from pathlib import Path

from anvyc.core.project_roots import resolve_project_roots


def _git_repos_under(base: Path, max_depth: int = 2) -> list[Path]:
    if not base.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and (entry / ".git").is_dir():
            out.append(entry)
    return out


def resolve_guard_targets(
    project: list[Path] | None, root: Path | None
) -> list[Path]:
    if project:
        return [p.expanduser().resolve() for p in project if (p / ".git").is_dir()]
    bases = [root.expanduser()] if root else [Path(r).expanduser() for r in resolve_project_roots()]
    seen: set[Path] = set()
    out: list[Path] = []
    for base in bases:
        for repo in _git_repos_under(base):
            r = repo.resolve()
            if r not in seen:
                seen.add(r)
                out.append(r)
    return out
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/integration/test_guard_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: 커밋**

```bash
git add src/anvyc/cli.py src/anvyc/core/guard_targets.py tests/integration/test_guard_cli.py
git commit -m "feat(guard): anvyc guard install — pre-push 가드 설치 CLI(--project/--root/--dry-run/--force)"
```

---

## Phase 3 — 서버 ruleset 적용 (anvyc, spec L2)

### Task 3.1: `git_protect` 모듈 — ruleset payload + gh api

**Files:**
- Create: `src/anvyc/core/git_protect.py`
- Test: `tests/unit/test_git_protect.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/unit/test_git_protect.py
"""Unit tests for anvyc.core.git_protect."""
from __future__ import annotations

import json
from unittest.mock import patch

from anvyc.core.git_protect import (
    RULESET_NAME,
    apply_ruleset,
    build_ruleset_payload,
    get_ruleset,
)


def test_payload_blocks_direct_push_with_pr_rule() -> None:
    p = build_ruleset_payload(required_reviews=0)
    assert p["name"] == RULESET_NAME
    assert p["enforcement"] == "active"
    assert p["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    types = {r["type"] for r in p["rules"]}
    assert {"pull_request", "non_fast_forward", "deletion"} <= types
    pr = next(r for r in p["rules"] if r["type"] == "pull_request")
    assert pr["parameters"]["required_approving_review_count"] == 0


def test_get_ruleset_matches_by_name() -> None:
    listing = json.dumps([{"id": 7, "name": RULESET_NAME}, {"id": 8, "name": "other"}])
    with patch("anvyc.core.git_protect._gh_api", return_value=(0, listing, "")):
        rs = get_ruleset("16bitdo", "anvyc")
    assert rs is not None and rs["id"] == 7


def test_apply_dry_run_would_create_when_absent() -> None:
    # 1) rulesets 목록 비어있음, 2) repo probe 성공
    with patch("anvyc.core.git_protect._gh_api", side_effect=[(0, "[]", ""), (0, "16bitdo/anvyc", "")]):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=True)
    assert res.action == "would-create"


def test_apply_no_access_when_repo_probe_404() -> None:
    with patch("anvyc.core.git_protect._gh_api", side_effect=[(0, "[]", ""), (1, "", "404 Not Found")]):
        res = apply_ruleset("whatap", "argus", dry_run=True)
    assert res.action == "no-access"


def test_apply_creates_when_not_dry_run() -> None:
    with patch(
        "anvyc.core.git_protect._gh_api",
        side_effect=[(0, "[]", ""), (0, "16bitdo/anvyc", ""), (0, '{"id":9}', "")],
    ):
        res = apply_ruleset("16bitdo", "anvyc", dry_run=False)
    assert res.action == "created"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_git_protect.py -v`
Expected: FAIL — `ModuleNotFoundError: anvyc.core.git_protect`

- [ ] **Step 3: 최소 구현**

```python
# src/anvyc/core/git_protect.py
"""GitHub repository ruleset 으로 서버측 PR 강제를 적용한다.

`anvyc guard protect` 가 활성 gh 계정으로 대상 repo 에 `anvyc-pr-required`
ruleset 을 생성/갱신한다. 직접 push 는 pull_request 규칙으로 차단된다.
접근 불가(whatap 등 404)는 no-access 로 분류해 silent 처리한다.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

RULESET_NAME = "anvyc-pr-required"


def build_ruleset_payload(*, required_reviews: int = 0) -> dict:
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": required_reviews,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                },
            },
        ],
        "bypass_actors": [],
    }


def _gh_api(args: list[str], *, input_str: str | None = None, timeout: int = 20) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["gh", "api", *args],
            input=input_str, capture_output=True, text=True, check=False, timeout=timeout,
        )
    except FileNotFoundError:
        return 127, "", "gh CLI not found"
    except subprocess.SubprocessError as e:
        return 1, "", str(e)
    return proc.returncode, proc.stdout, proc.stderr


def get_ruleset(owner: str, repo: str, name: str = RULESET_NAME) -> dict | None:
    rc, out, _ = _gh_api([f"repos/{owner}/{repo}/rulesets"])
    if rc != 0 or not out.strip():
        return None
    try:
        items = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not isinstance(items, list):
        return None
    for it in items:
        if isinstance(it, dict) and it.get("name") == name:
            return it
    return None


@dataclass
class ProtectResult:
    owner: str
    repo: str
    action: str  # created|updated|exists|would-create|would-update|no-access|error
    detail: str = ""


def apply_ruleset(owner: str, repo: str, *, required_reviews: int = 0, dry_run: bool = True) -> ProtectResult:
    existing = get_ruleset(owner, repo)
    payload = build_ruleset_payload(required_reviews=required_reviews)
    if existing is None:
        rc, _, err = _gh_api([f"repos/{owner}/{repo}", "--jq", ".full_name"])
        if rc != 0:
            return ProtectResult(owner, repo, "no-access", err.strip()[:80])
        if dry_run:
            return ProtectResult(owner, repo, "would-create")
        rc, _, err = _gh_api(
            [f"repos/{owner}/{repo}/rulesets", "--method", "POST", "--input", "-"],
            input_str=json.dumps(payload),
        )
        return ProtectResult(owner, repo, "created" if rc == 0 else "error", err.strip()[:120])
    if dry_run:
        return ProtectResult(owner, repo, "exists")
    rid = existing.get("id")
    rc, _, err = _gh_api(
        [f"repos/{owner}/{repo}/rulesets/{rid}", "--method", "PUT", "--input", "-"],
        input_str=json.dumps(payload),
    )
    return ProtectResult(owner, repo, "updated" if rc == 0 else "error", err.strip()[:120])
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_git_protect.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/git_protect.py tests/unit/test_git_protect.py
git commit -m "feat(guard): git_protect — repository ruleset payload + gh api(get/apply/no-access)"
```

### Task 3.2: `anvyc guard protect` CLI 커맨드 (기본 dry-run)

**Files:**
- Modify: `src/anvyc/cli.py` (guard_app 에 커맨드 추가)
- Create: `src/anvyc/utils/git_remote.py` 에 owner/repo 파서 없으면 추가 (있으면 재사용)
- Test: `tests/integration/test_guard_cli.py` (케이스 추가)

- [ ] **Step 1: 실패하는 통합 테스트 추가**

```python
# tests/integration/test_guard_cli.py 에 추가
def test_guard_protect_dry_run_default(tmp_path: Path) -> None:
    repo = _git_repo_with_origin(tmp_path / "proj", "git@github.com:16bitdo/proj.git")
    # gh 미인증/네트워크와 무관하게 dry-run 은 안전 종료해야 함(0 또는 안내).
    proc = run_anvyc("guard", "protect", "--project", str(repo), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "proj" in proc.stdout
    # 기본 dry-run: 실제 적용 단어("created") 미출력
    assert "created" not in proc.stdout
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/integration/test_guard_cli.py::test_guard_protect_dry_run_default -v`
Expected: FAIL — `No such command` 또는 출력 불일치

- [ ] **Step 3: owner/repo 파서 (재사용 우선)**

`anvyc/utils/git_remote.py` 에 owner/repo 추출이 없으면 추가:

```python
# src/anvyc/utils/git_remote.py 에 함수 추가 (기존 parse_git_config 옆)
import re
import subprocess
from pathlib import Path

_OWNER_REPO_RE = re.compile(
    r"(?:git@[^:]+:|https?://[^/]+/)([^/]+)/([^/]+?)(?:\.git)?/?$"
)


def origin_owner_repo(repo_dir: Path) -> tuple[str, str] | None:
    """origin remote URL 에서 (owner, repo) 추출. 실패 시 None."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    m = _OWNER_REPO_RE.search(proc.stdout.strip())
    return (m.group(1), m.group(2)) if m else None
```

- [ ] **Step 4: `protect` 커맨드 구현**

```python
@guard_app.command("protect")
def guard_protect(
    project: list[Path] | None = typer.Option(None, "--project", help="대상 repo 경로 (반복 가능)."),
    root: Path | None = typer.Option(None, "--root", help="스캔 상위 디렉터리."),
    apply: bool = typer.Option(False, "--apply", help="실제 적용 (기본: dry-run)."),
) -> None:
    """대상 repo 에 GitHub repository ruleset(PR 필수)을 적용한다. 기본 dry-run."""
    from anvyc.core.branch_policy import resolve_policy
    from anvyc.core.git_protect import apply_ruleset
    from anvyc.core.guard_targets import resolve_guard_targets
    from anvyc.utils.git_remote import origin_owner_repo

    targets = resolve_guard_targets(project, root)
    if not targets:
        console.print("[yellow]대상 repo 없음[/]")
        raise typer.Exit(code=0)

    for repo in targets:
        owner_repo = origin_owner_repo(repo)
        if owner_repo is None:
            console.print(f"[yellow]skip[/] {_short_path(repo)} (origin 없음)")
            continue
        owner, name = owner_repo
        policy = resolve_policy(repo)
        if policy.push_to_main_allowed:
            console.print(f"[dim]skip[/] {owner}/{name} (정책상 main push 허용)")
            continue
        res = apply_ruleset(owner, name, required_reviews=policy.pr_reviewers_min, dry_run=not apply)
        color = {"created": "green", "updated": "green", "exists": "dim",
                 "no-access": "dim"}.get(res.action, "yellow")
        console.print(f"[{color}]{res.action}[/] {owner}/{name} {res.detail}")
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/integration/test_guard_cli.py -v`
Expected: PASS (전체)

- [ ] **Step 6: 커밋**

```bash
git add src/anvyc/cli.py src/anvyc/utils/git_remote.py tests/integration/test_guard_cli.py
git commit -m "feat(guard): anvyc guard protect — repository ruleset 적용 CLI(기본 dry-run, --apply)"
```

---

## Phase 4 — doctor drift check (anvyc, spec L3)

### Task 4.1: `project-branch-protection` check

**Files:**
- Create: `src/anvyc/checks/project_branch_protection.py`
- Test: `tests/unit/test_project_branch_protection.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/unit/test_project_branch_protection.py
"""Unit tests for project-branch-protection check."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.project_branch_protection import ProjectBranchProtectionCheck
from anvyc.core.branch_policy import BranchPolicy

_PROTECTED = BranchPolicy(
    default_branch="main", protected_branches=("main",), push_to_main_allowed=False,
    pr_required=True, pr_reviewers_min=0, merge_strategy="squash", source="manifest",
)
_ALLOWED = BranchPolicy(
    default_branch="main", protected_branches=("main",), push_to_main_allowed=True,
    pr_required=False, pr_reviewers_min=0, merge_strategy="squash", source="manifest",
)


@pytest.fixture
def one_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / ".git" / "hooks").mkdir(parents=True)
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.resolve_guard_targets",
        lambda project, root: [repo],
    )
    monkeypatch.setattr(
        "anvyc.checks.project_branch_protection.origin_owner_repo",
        lambda d: ("16bitdo", "proj"),
    )
    return repo


def test_aligned_yields_info(one_repo: Path) -> None:
    (one_repo / ".git" / "hooks" / "pre-push").write_text("# >>> anvyc-pr-guard >>>\n")
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value={"id": 1}):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert all(r.severity is Severity.INFO for r in res)


def test_missing_ruleset_yields_warning(one_repo: Path) -> None:
    (one_repo / ".git" / "hooks" / "pre-push").write_text("# >>> anvyc-pr-guard >>>\n")
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value=None), \
         patch("anvyc.checks.project_branch_protection._has_repo_access", return_value=True):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert any(r.severity is Severity.WARNING and "ruleset" in r.message for r in res)


def test_missing_hook_yields_warning(one_repo: Path) -> None:
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value={"id": 1}):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert any(r.severity is Severity.WARNING and "hook" in r.message for r in res)


def test_allowed_repo_skipped(one_repo: Path) -> None:
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_ALLOWED):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert res == []


def test_no_access_silent(one_repo: Path) -> None:
    with patch("anvyc.checks.project_branch_protection.resolve_policy", return_value=_PROTECTED), \
         patch("anvyc.checks.project_branch_protection.get_ruleset", return_value=None), \
         patch("anvyc.checks.project_branch_protection._has_repo_access", return_value=False):
        res = ProjectBranchProtectionCheck().run(CheckContext())
    assert res == []  # whatap 등 접근 불가 → silent
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_project_branch_protection.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현**

```python
# src/anvyc/checks/project_branch_protection.py
"""project-branch-protection check (spec L3).

등록 프로젝트 중 정책상 보호 대상(push_to_main_allowed=false)인 repo 에 대해
① 서버 ruleset 존재 ② 로컬 pre-push 가드 설치 를 검증, 불일치 시 WARNING.
접근 불가(whatap 등)·정책상 허용 repo·origin 없음 → silent(결과 0건).
"""
from __future__ import annotations

from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.branch_policy import resolve_policy
from anvyc.core.git_guards import GUARD_BEGIN, effective_hooks_dir
from anvyc.core.git_protect import _gh_api, get_ruleset
from anvyc.core.guard_targets import resolve_guard_targets
from anvyc.utils.git_remote import origin_owner_repo


def _has_repo_access(owner: str, repo: str) -> bool:
    rc, _, _ = _gh_api([f"repos/{owner}/{repo}", "--jq", ".full_name"])
    return rc == 0


def _hook_installed(repo_dir: Path) -> bool:
    hooks_dir, tracked = effective_hooks_dir(repo_dir)
    if tracked:
        return True  # tracked hooksPath 는 repo 자체 도구 책임 → 위반으로 보지 않음
    hook = hooks_dir / "pre-push"
    return hook.is_file() and GUARD_BEGIN in hook.read_text(errors="replace")


class ProjectBranchProtectionCheck:
    name = "project-branch-protection"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        results: list[CheckResult] = []
        for repo in resolve_guard_targets(None, None):
            policy = resolve_policy(repo)
            if policy.push_to_main_allowed:
                continue  # 보호 대상 아님
            owner_repo = origin_owner_repo(repo)
            if owner_repo is None:
                continue
            owner, name = owner_repo
            ruleset = get_ruleset(owner, name)
            if ruleset is None and not _has_repo_access(owner, name):
                continue  # 접근 불가 → silent (whatap 등)

            problems: list[str] = []
            if ruleset is None:
                problems.append("서버 ruleset(anvyc-pr-required) 미설정")
            if not _hook_installed(repo):
                problems.append("로컬 pre-push hook 미설치")

            if problems:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=f"{owner}/{name}: " + " / ".join(problems),
                        location=repo,
                        suggestion="anvyc guard protect --apply / anvyc guard install",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.INFO,
                        message=f"{owner}/{name}: ruleset + pre-push 가드 정합",
                        location=repo,
                    )
                )
        return results
```

> **참고:** 테스트의 `"ruleset"`/`"hook"` 부분 문자열 assert 는 위 message(`서버 ruleset … 미설정`, `로컬 pre-push hook 미설치`)와 일치한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_project_branch_protection.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/checks/project_branch_protection.py tests/unit/test_project_branch_protection.py
git commit -m "feat(doctor): project-branch-protection check — ruleset/hook drift 관측(접근불가 silent)"
```

### Task 4.2: doctor `_REGISTRY` 등록 + 통합 검증

**Files:**
- Modify: `src/anvyc/core/doctor.py:50-73` (import + `_REGISTRY`)
- Test: `tests/integration/test_guard_cli.py` (doctor --only 케이스 추가)

- [ ] **Step 1: import 추가**

`doctor.py` 상단 check import 군에 추가:

```python
from anvyc.checks.project_branch_protection import ProjectBranchProtectionCheck
```

- [ ] **Step 2: `_REGISTRY` 에 등록**

`doctor.py:50-73` 의 `_REGISTRY` dict 끝(work-cwd-track 다음)에 추가:

```python
    "work-cwd-track-wired": WorkCwdTrackWiredCheck(),
    "project-branch-protection": ProjectBranchProtectionCheck(),
}
```

- [ ] **Step 3: 통합 테스트 추가**

```python
# tests/integration/test_guard_cli.py 에 추가
def test_doctor_only_branch_protection_runs(tmp_path: Path) -> None:
    proc = run_anvyc("doctor", "--json", "--only", "project-branch-protection", cwd=tmp_path)
    assert proc.returncode in (0, 1), proc.stderr
    import json
    data = json.loads(proc.stdout)
    names = {r["check_name"] for r in data["results"]}
    assert names <= {"project-branch-protection"}  # 다른 check 미혼입 (0건도 허용)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/integration/test_guard_cli.py::test_doctor_only_branch_protection_runs -v`
Expected: PASS

- [ ] **Step 5: 전체 단위/통합 회귀**

Run: `python -m pytest tests/unit tests/integration -q`
Expected: 전체 PASS (신규 5개 모듈/테스트 포함)

- [ ] **Step 6: 커밋**

```bash
git add src/anvyc/core/doctor.py tests/integration/test_guard_cli.py
git commit -m "feat(doctor): project-branch-protection 을 _REGISTRY 에 등록 + 통합 테스트"
```

---

## Phase 5 — 문서화 + 운영 롤아웃 (spec L4 + 롤아웃)

### Task 5.1: DESIGN.md / spec 상태 갱신

**Files:**
- Modify: `DESIGN.md` (신규 control-plane 항목)
- Modify: `docs/superpowers/specs/2026-06-01-pr-workflow-enforcement-design.md` (상태: 구현 완료)

- [ ] **Step 1: DESIGN.md 에 control-plane 항목 추가** — 기존 CP 표/섹션 형식을 따라 "branch policy 강제(guard install/protect + project-branch-protection)" 항목 1개 추가. `anvyc guard` 커맨드, `branch_policy/git_guards/git_protect` 모듈, check 이름 명시.

- [ ] **Step 2: spec 헤더 상태 변경** — `상태: 승인됨 (구현 플랜 대기)` → `상태: 구현 완료 (2026-06-02)`.

- [ ] **Step 3: 커밋**

```bash
git add DESIGN.md docs/superpowers/specs/2026-06-01-pr-workflow-enforcement-design.md
git commit -m "docs(guard): branch policy 강제 control-plane 항목 + spec 상태 갱신"
```

### Task 5.2: 운영 롤아웃 — Phase B 확인 게이트(1개 선적용)

> 코드가 아닌 **실행 절차**. anvyc 변경 머지 후 수행. 각 단계는 read-only 검증 → 변경 → 사후검증.

- [ ] **Step 1: dry-run 전수 미리보기**

Run: `anvyc guard protect --root ~/dev`
Expected: 16개 16bitdo repo `would-create`, whatap 6개 `no-access`(silent/dim), 정책 허용 repo `skip`.

- [ ] **Step 2: 저위험 1개(security-scan) 선적용**

Run: `anvyc guard protect --project ~/dev/security-scan --apply`
Expected: `created 16bitdo/security-scan`.

- [ ] **Step 3: 서버 적용 사후검증 + 직접 push reject 실측**

```bash
gh api repos/16bitdo/security-scan/rulesets --jq '.[].name'   # anvyc-pr-required 포함 확인
git -C ~/dev/security-scan switch -c chore/guard-smoke && \
  git -C ~/dev/security-scan commit --allow-empty -m "smoke" && \
  git -C ~/dev/security-scan push origin HEAD:main   # ← 서버가 reject 해야 정상
```
Expected: main 직접 push **reject**(`protected branch`/`pull request required`). 브랜치 push 는 통과.
롤백(필요 시): `gh api repos/16bitdo/security-scan/rulesets/<id> -X DELETE`.

### Task 5.3: 운영 롤아웃 — 나머지 15개 일괄 + 로컬 hook

- [ ] **Step 1: 나머지 15개 ruleset 일괄 적용**

Run: `anvyc guard protect --root ~/dev --apply`
Expected: 15개 추가 `created`(security-scan 은 `exists`), whatap `no-access`.

- [ ] **Step 2: 16개 전수 서버 사후검증**

```bash
for r in aiforge analysis anvyc anvyc-internal anvyx api-test-hub architecture ccinspector ctxport cursor-ide dotfiles-claude homebrew-anvyc pulumi-dev rca role-based-ruleset security-scan; do
  printf "%-22s " "$r"; gh api repos/16bitdo/$r/rulesets --jq '[.[].name]' 2>/dev/null
done
```
Expected: 16개 모두 `["anvyc-pr-required"]` 포함.

- [ ] **Step 3: 로컬 pre-push 가드 일괄 설치**

Run: `anvyc guard install --root ~/dev`
Expected: 16개 `installed`. role-based-ruleset 은 tracked hooksPath 면 `skipped-tracked-hooks`(정상 — 서버 ruleset 으로 커버).

- [ ] **Step 4: doctor drift 0 확인**

Run: `anvyc doctor --only project-branch-protection --verbose`
Expected: WARNING 0건(전부 INFO 정합). 잔여 WARNING 있으면 해당 repo 재적용.

- [ ] **Step 5: anvyc 작업 브랜치 PR**

```bash
cd ~/dev/anvyc
git push -u origin feat/pr-workflow-enforcement
gh pr create --fill --base main
```
Expected: PR URL. (Phase 1 의 role-based-ruleset PR 과 함께 머지.)

---

## Self-Review (작성자 점검 결과)

**1. Spec coverage:** spec L0→Phase1, L1→Phase2(branch_policy+git_guards+install), L2→Phase3(git_protect+protect), L3→Phase4(check+등록), L4→Task5.1(generate_claude_md 는 Task1.2), 롤아웃 A~E→Task5.2~5.3. 누락 없음.

**2. Placeholder scan:** "TBD/적절히 처리" 없음. 모든 코드 step 에 실제 코드 포함. 운영 Task(5.2/5.3)는 코드 아닌 검증 명령으로 구성(의도적).

**3. Type consistency:** `BranchPolicy`(7필드) 전 Phase 동일. `resolve_policy`/`install_pre_push_guard`/`apply_ruleset`/`get_ruleset`/`_gh_api`/`resolve_guard_targets`/`origin_owner_repo`/`GUARD_BEGIN`/`effective_hooks_dir` 시그니처가 정의 Task 와 소비 Task(check/CLI)에서 일치. check 의 부분문자열 assert("ruleset"/"hook")가 message 와 일치 확인.

**4. Ambiguity:** `guard` sub-app 신규(기존 `git` 은 .anvyc 전용)·dry-run 기본·tracked hooksPath skip·no-access silent 모두 명시.

알려진 가정(구현 중 1회 검증): ① GitHub repository ruleset POST 가 free private repo 에서 수락되는지 → Task 5.2 Step2 가 확인 게이트. ② `gh api .../rulesets` 페이로드 키(`~DEFAULT_BRANCH` 등)는 현행 API 기준; 거부 시 payload 조정.
