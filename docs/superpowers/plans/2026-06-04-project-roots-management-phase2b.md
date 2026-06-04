# 소비처 통합 (Phase 2b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 나머지 8개 프로젝트-스캔 소비처(doctor 5 check·guard·cursor-suggest·MCP project_list)를 `core/project_scope.py iter_project_dirs` 로 전환해, `projects`(개별 포함)/`exclude_projects`(개별 제외) 가 anvyc 전반에서 honoring 되게 한다.

**Architecture:** Phase 2a 의 `iter_project_dirs(config, *, markers, max_depth)` 를 각 소비처의 자체 스캔(`_iter_*`/inline iterdir)으로 **대체**한다. **동작 보존**이 최우선 — 기존 테스트가 회귀 가드. 각 소비처는 자기 marker 와 보존 max_depth 로 호출하고, 기존 소비 로직(파일 읽기/origin 파싱 등)은 유지한다.

**Tech Stack:** Python 3.11+, pytest.

**Spec:** `docs/superpowers/specs/2026-06-04-project-roots-management-design.md` (§8 소비처 통합 표)

---

## ⚠️ 공통 Refactor 패턴 (모든 소비처 태스크의 전제 — 숙지 필수)

### (P1) 깊이 매핑 — 동작 보존의 핵심
기존 5개 check 의 `_iter_*` 는 `rglob(marker)` + `len(rel.parts) > _MAX_DEPTH(3)` 으로 **marker 파일의 경로 parts** 를 센다. `iter_project_dirs._walk_markers` 는 **디렉터리 깊이**(root 의 자식=depth 1)를 센다. marker-parts = dir-depth + 1 이므로:

| 기존 스캔 | iter_project_dirs `max_depth` |
|-----------|-------------------------------|
| `_MAX_DEPTH=3` (marker rglob: gh/aws/claude/pulumi/unused) | **2** |
| depth-1 `iterdir` (guard `_git_repos_under`, cursor inline) | **1** |
| MCP `discover_projects` (이미 max_depth=2) | **2** |

**검증**: `root/a/b/.git`(marker-parts 3, dir `b` 는 dir-depth 2) → 기존 included, `max_depth=2` 도 included. `root/a/b/c/.git`(parts 4, dir-depth 3) → 기존 excluded, `max_depth=2` 도 excluded. 일치. **각 태스크는 반드시 위 표의 max_depth 를 사용한다.**

### (P2) 파일 marker vs 디렉터리 marker 소비 변환
`iter_project_dirs` 는 **디렉터리**(marker 보유)를 반환한다. 기존이 marker **파일**(`.envrc`/`Pulumi.yaml`)을 순회했다면, 새 코드는 `project_dir / "<marker>"` 로 파일에 접근한다. 기존이 marker **디렉터리**(`.git`/`.cursor`)였다면 `project_dir / ".git"` 또는 `project_dir` 를 쓴다. iter_project_dirs 가 이미 `resolve()` dedup·정렬하므로 기존 `seen` set dedup 로직은 제거한다.

### (P3) 테스트 monkeypatch 이전 — 필수
기존 check 테스트는 `anvyc.checks.<X>.resolve_project_roots` 를 monkeypatch 한다. refactor 후 check 는 `resolve_project_roots` 를 직접 부르지 않고 `iter_project_dirs` 를 부르며, 그 안에서 `anvyc.core.project_roots.{resolve_project_roots,resolve_projects,resolve_excludes}` 를 **lazy import** 한다. 따라서 각 테스트 fixture 의 monkeypatch 를 아래로 **이전**한다:

```python
# (기존) anvyc.checks.<X>.resolve_project_roots 패치 → (신규) core 모듈 3종 패치:
monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(root),))
monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: ())
monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
```
(`resolve_projects`/`resolve_excludes` 를 `()` 로 고정해 실제 사용자 config 의 projects/excludes 누수 차단 — 헤르메틱.)

### (P4) stop-at-marker 정제
`_walk_markers` 는 marker 발견 시 하강을 멈춘다(프로젝트의 하위 디렉터리는 별도 프로젝트 아님). 기존 rglob 은 중첩 marker 도 모두 찾았다. 기존 테스트는 단순 1~2단 구조라 영향 없음 — 의도된 정제로 수용.

### (P5) helper 삭제 + 순서
refactor 후 죽은 `_iter_*` helper 를 삭제한다. **`project_aws_profile._iter_envrcs` 는 `unused_aws_profiles` 가 import** 하므로, **unused 를 먼저**(Task 1) refactor 해 import 를 끊은 뒤 aws(Task 2)에서 삭제한다. `_read_envrc_profile`(aws) 은 unused 가 계속 쓰므로 **보존**.

---

## Branch 설정 (구현 시작 전 1회)

```bash
cd ~/dev/anvyc
git switch main && GIT_SSH_COMMAND='ssh -o IdentityAgent=none -o IdentitiesOnly=yes' git pull --ff-only
git switch -c feat/consumers-phase2b
```
> SSH agent 이슈 시 push: `GIT_SSH_COMMAND='ssh -o IdentityAgent=none -o IdentitiesOnly=yes' git push ...`

## File Structure

| 파일 | 변경 |
|------|------|
| `src/anvyc/checks/unused_aws_profiles.py` | run() 스캔 → iter_project_dirs(.envrc, depth=2); `_iter_envrcs` import 제거(`_read_envrc_profile` 유지) |
| `src/anvyc/checks/project_aws_profile.py` | run() → iter_project_dirs(.envrc, 2); `_iter_envrcs` 삭제 |
| `src/anvyc/checks/project_claude_account.py` | run() → iter_project_dirs(.envrc, 2); `_iter_envrc_files` 삭제 (들여쓰기 버그 동시 해소) |
| `src/anvyc/checks/project_pulumi_backend.py` | run() → iter_project_dirs(Pulumi.yaml, 2); `_iter_pulumi_yaml` 삭제 |
| `src/anvyc/checks/project_gh_account.py` | run() → iter_project_dirs(.git, 2); `_iter_git_dirs` 삭제 |
| `src/anvyc/core/guard_targets.py` | resolve_guard_targets no-arg 분기 → iter_project_dirs(.git, 1); `_git_repos_under` 삭제 |
| `src/anvyc/checks/cursor_projects_suggest.py` | inline 스캔 → iter_project_dirs(.cursor, 1) (config-aware 화) |
| `src/anvyc/mcp/server.py` | project_list no-roots 분기 → iter_project_dirs(PROJECT_MARKERS, 2) |
| 각 `tests/unit/test_*.py` | fixture monkeypatch 이전(P3) + projects-honored 테스트 추가 |

---

## Task 1: `unused_aws_profiles` → iter_project_dirs

**Files:**
- Modify: `src/anvyc/checks/unused_aws_profiles.py:29-42`
- Test: `tests/unit/test_unused_aws_profiles.py`

현재 run() 스캔(참조):
```python
        from anvyc.checks.project_aws_profile import _iter_envrcs, _read_envrc_profile
        from anvyc.core.project_roots import resolve_project_roots

        used: set[str] = set()
        for root_str in resolve_project_roots():
            root = Path(root_str).expanduser()
            for envrc in _iter_envrcs(root):
                prof = _read_envrc_profile(envrc)
                if prof:
                    used.add(prof)
```

- [ ] **Step 1: projects-honored 테스트 추가 (실패 예상)**

```python
# tests/unit/test_unused_aws_profiles.py 에 추가 (import 는 파일 상단으로)
def test_unused_honors_individual_project(tmp_path, monkeypatch) -> None:
    # 컨테이너는 비우고, 개별 project 의 .envrc 가 profile 을 '사용 중'으로 만든다
    import textwrap
    aws_cfg = tmp_path / "aws_config"
    aws_cfg.write_text("[profile used-prof]\n[profile lonely]\n")
    monkeypatch.setattr("anvyc.utils.aws_config.DEFAULT_AWS_CONFIG", aws_cfg)
    empty = tmp_path / "empty"; empty.mkdir()
    indiv = tmp_path / "proj"; indiv.mkdir()
    (indiv / ".envrc").write_text("export AWS_PROFILE=used-prof\n")
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(empty),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    from anvyc.checks.unused_aws_profiles import UnusedAwsProfilesCheck
    results = UnusedAwsProfilesCheck().run(None)
    msg = " ".join(r.message for r in results)
    assert "lonely" in msg and "used-prof" not in msg  # used-prof 는 개별 project 가 사용
```

- [ ] **Step 2: Run — 실패 확인**

Run: `.venv/bin/pytest tests/unit/test_unused_aws_profiles.py::test_unused_honors_individual_project -v`
Expected: FAIL (현재 check 는 개별 project 를 스캔 안 함 → used-prof 미검출 → "used-prof" 가 unused 로 잘못 표시되거나 assert 실패)

- [ ] **Step 3: refactor run()**

`src/anvyc/checks/unused_aws_profiles.py` 의 deferred import + 스캔 루프를 교체:
```python
        from anvyc.checks.project_aws_profile import _read_envrc_profile
        from anvyc.core.project_scope import iter_project_dirs

        used: set[str] = set()
        for project_dir in iter_project_dirs(markers=(".envrc",), max_depth=2):
            prof = _read_envrc_profile(project_dir / ".envrc")
            if prof:
                used.add(prof)
```
(`_iter_envrcs`/`resolve_project_roots`/`Path` deferred import 제거 — `Path` 가 다른 곳에서 안 쓰이면 함께 제거. ruff F401 로 확인.)

- [ ] **Step 4: 기존 테스트 fixture monkeypatch 이전 + 전체 통과**

`tests/unit/test_unused_aws_profiles.py` 의 fixture monkeypatch 를 P3 형태로 변경: `anvyc.core.project_roots.resolve_project_roots` (이미 core 패치 — unused 는 원래 deferred 라 core 패치였음) + `resolve_projects`/`resolve_excludes` → `()` 2줄 추가.
Run: `.venv/bin/pytest tests/unit/test_unused_aws_profiles.py -v`
Expected: PASS (기존 + 신규)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/checks/unused_aws_profiles.py tests/unit/test_unused_aws_profiles.py
git commit -m "refactor(unused-aws): iter_project_dirs 전환 — projects/excludes honoring"
```

---

## Task 2: `project_aws_profile` → iter_project_dirs + `_iter_envrcs` 삭제

**Files:**
- Modify: `src/anvyc/checks/project_aws_profile.py` (run 64-78 + `_iter_envrcs` 29-47 삭제)
- Test: `tests/unit/test_project_aws_profile.py`

- [ ] **Step 1: projects-honored 테스트 추가**

```python
# tests/unit/test_project_aws_profile.py 에 추가
def test_aws_profile_honors_individual_project(tmp_path, monkeypatch) -> None:
    aws_cfg = tmp_path / "aws_config"; aws_cfg.write_text("[profile defined-p]\n")
    monkeypatch.setattr("anvyc.utils.aws_config.DEFAULT_AWS_CONFIG", aws_cfg)
    empty = tmp_path / "empty"; empty.mkdir()
    indiv = tmp_path / "proj"; indiv.mkdir()
    (indiv / ".envrc").write_text("export AWS_PROFILE=undefined-p\n")
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(empty),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    from anvyc.checks.project_aws_profile import ProjectAwsProfileMappingCheck
    results = ProjectAwsProfileMappingCheck().run(None)
    assert any("undefined-p" in r.message for r in results)  # 개별 project 의 미정의 profile 경고
```

- [ ] **Step 2: Run — 실패 확인**

Run: `.venv/bin/pytest tests/unit/test_project_aws_profile.py::test_aws_profile_honors_individual_project -v`
Expected: FAIL (개별 project 미스캔)

- [ ] **Step 3: refactor run() + `_iter_envrcs` 삭제**

run() 의 스캔 루프(64-78, `envrcs`/`seen` 구성)를 교체:
```python
        from anvyc.core.project_scope import iter_project_dirs

        mappings: list[tuple[Path, str]] = []
        for project_dir in iter_project_dirs(markers=(".envrc",), max_depth=2):
            prof = _read_envrc_profile(project_dir / ".envrc")
            if prof:
                mappings.append((project_dir / ".envrc", prof))
```
(이후 기존 `for e in envrcs: ...` 블록은 위 mappings 구성에 흡수 — 중복 루프 제거. 기존 `mappings` 사용부는 유지.) `_iter_envrcs`(29-47) 정의 삭제. 모듈 상단 `resolve_project_roots` import 가 더 안 쓰이면 삭제(ruff 확인). `_read_envrc_profile` 은 유지.

- [ ] **Step 4: fixture 이전 + 전체 통과**

fixture 의 `anvyc.checks.project_aws_profile.resolve_project_roots` 패치를 P3 의 core 3종으로 교체.
Run: `.venv/bin/pytest tests/unit/test_project_aws_profile.py tests/unit/test_unused_aws_profiles.py -v`
Expected: PASS (unused 도 _iter_envrcs 미import 확인)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/checks/project_aws_profile.py tests/unit/test_project_aws_profile.py
git commit -m "refactor(aws-profile): iter_project_dirs 전환 + _iter_envrcs 삭제"
```

---

## Task 3: `project_claude_account` → iter_project_dirs + 들여쓰기 버그 해소

**Files:**
- Modify: `src/anvyc/checks/project_claude_account.py` (run 73-93 + `_iter_envrc_files` 37-54 삭제)
- Test: `tests/unit/test_project_claude_account.py`

> NOTE: 현재 run() 의 `envrc_files.append(e)`(line 86)가 inner loop 밖에 있어 root 당 마지막 .envrc 만 수집되는 버그가 있다. 본 refactor 가 루프를 교체하며 자연 해소된다.

- [ ] **Step 1: projects-honored 테스트 추가**

```python
# tests/unit/test_project_claude_account.py 에 추가
def test_claude_honors_individual_project(tmp_path, monkeypatch) -> None:
    empty = tmp_path / "empty"; empty.mkdir()
    indiv = tmp_path / "proj"; indiv.mkdir()
    missing_dir = tmp_path / "nope"   # 존재하지 않는 CLAUDE_CONFIG_DIR
    (indiv / ".envrc").write_text(f'export CLAUDE_CONFIG_DIR="{missing_dir}"\n')
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(empty),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    from anvyc.checks.project_claude_account import ProjectClaudeAccountMappingCheck
    results = ProjectClaudeAccountMappingCheck().run(None)
    assert any(str(missing_dir) in (r.message + str(r.suggestion or "")) or "proj" in r.message for r in results)
```

- [ ] **Step 2: Run — 실패 확인**

Run: `.venv/bin/pytest tests/unit/test_project_claude_account.py::test_claude_honors_individual_project -v`
Expected: FAIL

- [ ] **Step 3: refactor run() + `_iter_envrc_files` 삭제**

run() 의 스캔 루프(73-86)를 교체:
```python
        from anvyc.core.project_scope import iter_project_dirs

        targets: list[tuple[Path, str]] = []
        for project_dir in iter_project_dirs(markers=(".envrc",), max_depth=2):
            raw = _read_envrc_claude_dir(project_dir / ".envrc")
            if raw:
                targets.append((project_dir, raw))
```
(기존 `envrc_files` 수집 + `for envrc in envrc_files:` 블록을 위로 흡수. 이후 `targets` 사용부 유지.) `_iter_envrc_files`(37-54) 삭제. 모듈 `resolve_project_roots` import 미사용 시 삭제.

- [ ] **Step 4: fixture 이전 + 전체 통과**

fixture monkeypatch 를 P3 core 3종으로 교체.
Run: `.venv/bin/pytest tests/unit/test_project_claude_account.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/checks/project_claude_account.py tests/unit/test_project_claude_account.py
git commit -m "refactor(claude-account): iter_project_dirs 전환 + _iter_envrc_files 삭제(들여쓰기 버그 해소)"
```

---

## Task 4: `project_pulumi_backend` → iter_project_dirs + `_iter_pulumi_yaml` 삭제

**Files:**
- Modify: `src/anvyc/checks/project_pulumi_backend.py` (run 67-93 + `_iter_pulumi_yaml` 34-51 삭제)
- Test: `tests/unit/test_project_pulumi_backend.py`

- [ ] **Step 1: projects-honored 테스트 추가**

```python
# tests/unit/test_project_pulumi_backend.py 에 추가
def test_pulumi_honors_individual_project(tmp_path, monkeypatch) -> None:
    empty = tmp_path / "empty"; empty.mkdir()
    indiv = tmp_path / "proj"; indiv.mkdir()
    (indiv / "Pulumi.yaml").write_text("name: p\nruntime: python\nbackend:\n  url: s3://yaml-be\n")
    (indiv / ".envrc").write_text('export PULUMI_BACKEND_URL="s3://envrc-be"\n')  # mismatch
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(empty),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    from anvyc.checks.project_pulumi_backend import ProjectPulumiBackendMappingCheck
    results = ProjectPulumiBackendMappingCheck().run(None)
    assert any("proj" in r.message for r in results)  # 개별 project 가 스캔되어 mismatch 경고
```

- [ ] **Step 2: Run — 실패 확인**

Run: `.venv/bin/pytest tests/unit/test_project_pulumi_backend.py::test_pulumi_honors_individual_project -v`
Expected: FAIL

- [ ] **Step 3: refactor run() + `_iter_pulumi_yaml` 삭제**

run() 의 스캔 루프(67-80)를 교체:
```python
        from anvyc.core.project_scope import iter_project_dirs

        targets: list[tuple[Path, str | None, str | None]] = []
        for project_dir in iter_project_dirs(markers=("Pulumi.yaml",), max_depth=2):
            info = detect_pulumi_project(project_dir)
            yaml_backend = info.backend_url if info else None
            envrc = project_dir / ".envrc"
            envrc_backend = _read_envrc_pulumi_backend(envrc) if envrc.is_file() else None
            if yaml_backend or envrc_backend:
                targets.append((project_dir, yaml_backend, envrc_backend))
```
(기존 `yaml_files`/`seen` 수집 + `for yaml_path in yaml_files:` 블록을 흡수 — `project_dir = yaml_path.parent` 가 곧 iter 결과.) `_iter_pulumi_yaml`(34-51) 삭제. `resolve_project_roots` import 미사용 시 삭제.

- [ ] **Step 4: fixture 이전 + 전체 통과**

fixture monkeypatch 를 P3 core 3종으로 교체.
Run: `.venv/bin/pytest tests/unit/test_project_pulumi_backend.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/checks/project_pulumi_backend.py tests/unit/test_project_pulumi_backend.py
git commit -m "refactor(pulumi-backend): iter_project_dirs 전환 + _iter_pulumi_yaml 삭제"
```

---

## Task 5: `project_gh_account` → iter_project_dirs + `_iter_git_dirs` 삭제

**Files:**
- Modify: `src/anvyc/checks/project_gh_account.py` (run 123-149 + `_iter_git_dirs` 37-55 삭제)
- Test: `tests/unit/test_project_gh_account.py`

- [ ] **Step 1: projects-honored 테스트 추가**

```python
# tests/unit/test_project_gh_account.py 에 추가 (기존 테스트의 .git/config + ssh alias 셋업 헬퍼 재사용)
def test_gh_honors_individual_project(tmp_path, monkeypatch) -> None:
    empty = tmp_path / "empty"; empty.mkdir()
    indiv = tmp_path / "proj"; (indiv / ".git").mkdir(parents=True)
    (indiv / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com-16bitdo:16bitdo/x.git\n'
    )
    # .envrc 에 GH_CONFIG_DIR 없음 → alias 라우팅 누락 경고 기대
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(empty),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    from anvyc.checks.project_gh_account import ProjectGhAccountMappingCheck
    results = ProjectGhAccountMappingCheck().run(None)
    assert any("proj" in r.message or "16bitdo" in r.message for r in results)
```

- [ ] **Step 2: Run — 실패 확인**

Run: `.venv/bin/pytest tests/unit/test_project_gh_account.py::test_gh_honors_individual_project -v`
Expected: FAIL

- [ ] **Step 3: refactor run() + `_iter_git_dirs` 삭제**

run() 의 스캔 루프(123-136, `git_dirs`/`seen` 구성)를 교체. 이후 소비부(143-149)는 `git_dir = project_dir / ".git"` 로 접근:
```python
        from anvyc.core.project_scope import iter_project_dirs

        project_dirs = iter_project_dirs(markers=(".git",), max_depth=2)
        # ... (기존 targets/routing_targets 구성)
        for project_dir in project_dirs:
            info = _origin_routing(project_dir / ".git")
            if info:
                alias, owner, repo = info
                targets.append((project_dir, alias))
                if owner and repo:
                    routing_targets.append((project_dir, alias, owner, repo))
```
(기존 `for git_dir in git_dirs: ... git_dir.parent` 를 위 형태로 — `git_dir.parent` == `project_dir`.) `_iter_git_dirs`(37-55) 삭제. `resolve_project_roots` import 미사용 시 삭제.

- [ ] **Step 4: fixture 이전 + 전체 통과**

fixture monkeypatch 를 P3 core 3종으로 교체.
Run: `.venv/bin/pytest tests/unit/test_project_gh_account.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/checks/project_gh_account.py tests/unit/test_project_gh_account.py
git commit -m "refactor(gh-account): iter_project_dirs 전환 + _iter_git_dirs 삭제"
```

---

## Task 6: `guard_targets` → iter_project_dirs + `_git_repos_under` 삭제

**Files:**
- Modify: `src/anvyc/core/guard_targets.py` (resolve_guard_targets 20-35 + `_git_repos_under` 10-17 삭제)
- Test: `tests/unit/test_guard_targets.py` (없으면 생성)

- [ ] **Step 1: projects-honored 테스트 추가**

```python
# tests/unit/test_guard_targets.py
from pathlib import Path
import pytest
from anvyc.core.guard_targets import resolve_guard_targets


def test_guard_honors_individual_project(tmp_path, monkeypatch) -> None:
    empty = tmp_path / "empty"; empty.mkdir()
    indiv = tmp_path / "proj"; (indiv / ".git").mkdir(parents=True)
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(empty),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    targets = resolve_guard_targets(None, None)
    assert indiv.resolve() in targets


def test_guard_explicit_project_unchanged(tmp_path) -> None:
    indiv = tmp_path / "p"; (indiv / ".git").mkdir(parents=True)
    assert resolve_guard_targets([indiv], None) == [indiv.resolve()]
```

- [ ] **Step 2: Run — 실패 확인**

Run: `.venv/bin/pytest tests/unit/test_guard_targets.py -v`
Expected: FAIL (`test_guard_honors_individual_project` — 개별 미스캔)

- [ ] **Step 3: refactor resolve_guard_targets + `_git_repos_under` 삭제**

`src/anvyc/core/guard_targets.py` 의 no-project 분기(26-35)를 교체. `--project`(23-25), `--root` 분기는 유지:
```python
def resolve_guard_targets(project: list[Path] | None, root: Path | None) -> list[Path]:
    from anvyc.core.project_scope import iter_project_dirs

    if project:
        expanded = [p.expanduser().resolve() for p in project]
        return [p for p in expanded if (p / ".git").is_dir()]
    if root:
        base = root.expanduser()
        return [
            d.resolve() for d in sorted(base.iterdir())
            if d.is_dir() and (d / ".git").is_dir()
        ] if base.is_dir() else []
    return iter_project_dirs(markers=(".git",), max_depth=1)
```
(`_git_repos_under`(10-17) 삭제 — `--root` 분기는 inline 으로 흡수. 모듈 상단 `resolve_project_roots` import 미사용 시 삭제.)

- [ ] **Step 4: 회귀 — branch-protection check 도 통과**

Run: `.venv/bin/pytest tests/unit/test_guard_targets.py tests/unit/test_project_branch_protection.py tests/unit/test_git_protect.py -v`
Expected: PASS (resolve_guard_targets 소비처 회귀)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/guard_targets.py tests/unit/test_guard_targets.py
git commit -m "refactor(guard-targets): iter_project_dirs 전환 + _git_repos_under 삭제"
```

---

## Task 7: `cursor_projects_suggest` → iter_project_dirs (config-aware)

**Files:**
- Modify: `src/anvyc/checks/cursor_projects_suggest.py:41-62`
- Test: `tests/unit/test_cursor_projects_suggest.py` (없으면 생성)

> NOTE: 현재 cursor-suggest 는 `DEFAULT_PROJECT_ROOTS` 를 직접 써 사용자 `project_roots` config 를 무시한다. iter_project_dirs 전환으로 **config-aware** 가 되고(사용자 roots 존중) projects/excludes 도 honoring — 의도된 개선.

- [ ] **Step 1: 테스트 추가**

```python
# tests/unit/test_cursor_projects_suggest.py
from pathlib import Path

import pytest

from anvyc.checks.cursor_projects_suggest import CursorProjectsSuggestCheck
from anvyc.core.config import AnvycConfig


def test_cursor_suggest_honors_roots_and_excludes(tmp_path, monkeypatch) -> None:
    container = tmp_path / "dev"
    (container / "p1" / ".cursor").mkdir(parents=True)
    (container / "p2" / ".cursor").mkdir(parents=True)
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(container),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: ())
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: (str(container / "p2"),))
    # 등록 roots 비움(중복 제안 회피 로직): load_anvyc_config 를 빈 config 로
    monkeypatch.setattr("anvyc.core.config.load_anvyc_config", lambda *a, **k: AnvycConfig())
    results = CursorProjectsSuggestCheck().run(None)
    msg = " ".join(r.message for r in results)
    assert "p1" in msg and "p2" not in msg  # p2 는 exclude
```

- [ ] **Step 2: Run — 실패 확인**

Run: `.venv/bin/pytest tests/unit/test_cursor_projects_suggest.py -v`
Expected: FAIL (현재 exclude 미적용 → p2 포함)

- [ ] **Step 3: refactor inline 스캔**

`src/anvyc/checks/cursor_projects_suggest.py` 의 inline 스캔(41-62)을 교체. `registered`(중복 제안 회피) 필터는 유지:
```python
        from anvyc.core.project_scope import iter_project_dirs

        discovered: list[Path] = []
        for entry in iter_project_dirs(markers=(".cursor",), max_depth=1):
            try:
                resolved = entry.resolve()
            except OSError:
                continue
            if resolved in registered:
                continue
            discovered.append(entry)
```
(상단 `from anvyc.core.project_roots import DEFAULT_PROJECT_ROOTS` 가 더 안 쓰이면 삭제 — ruff 확인.)

- [ ] **Step 4: 통과**

Run: `.venv/bin/pytest tests/unit/test_cursor_projects_suggest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/checks/cursor_projects_suggest.py tests/unit/test_cursor_projects_suggest.py
git commit -m "refactor(cursor-suggest): iter_project_dirs 전환 — config-aware + excludes honoring"
```

---

## Task 8: MCP `project_list` → iter_project_dirs (CLI parity)

**Files:**
- Modify: `src/anvyc/mcp/server.py:266-274`
- Test: `tests/integration/test_mcp_server.py` (회귀) + 신규 unit

- [ ] **Step 1: projects-honored 테스트 추가**

```python
# tests/unit/test_mcp_project_list_scope.py
from pathlib import Path
import pytest


def test_mcp_project_list_honors_projects(tmp_path, monkeypatch) -> None:
    container = tmp_path / "dev"
    (container / "p1" / ".git").mkdir(parents=True)
    indiv = tmp_path / "work" / "x"; (indiv / ".git").mkdir(parents=True)
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(container),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    from anvyc.mcp.server import _dispatch
    result = _dispatch("project_list", {})  # roots 미지정 → iter_project_dirs
    names = {Path(e["path"]).name for e in result}
    assert "p1" in names and "x" in names
```

- [ ] **Step 2: Run — 실패 확인**

Run: `.venv/bin/pytest tests/unit/test_mcp_project_list_scope.py -v`
Expected: FAIL (개별 x 미포함)

- [ ] **Step 3: refactor project_list 핸들러**

`src/anvyc/mcp/server.py:266-274` 의 분기를 교체:
```python
    if name == "project_list":
        from anvyc.core.project_discovery import PROJECT_MARKERS, discover_projects
        from anvyc.core.project_info import collect_project_info, to_dict
        from anvyc.core.project_scope import iter_project_dirs

        explicit = args.get("roots")
        if explicit:
            projs = discover_projects(list(explicit))  # 명시 override
        else:
            projs = iter_project_dirs(markers=PROJECT_MARKERS, max_depth=2)
        reveal = bool(args.get("reveal_secrets", False))
        return [to_dict(collect_project_info(p, redact_secrets=not reveal)) for p in projs]
```

- [ ] **Step 4: 통과 + 통합 회귀**

Run: `.venv/bin/pytest tests/unit/test_mcp_project_list_scope.py -v`
Expected: PASS
Run(통합, 가능 시): `.venv/bin/pytest tests/integration/test_mcp_server.py -k project_list -v`
Expected: PASS (명시 roots 분기 보존)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/mcp/server.py tests/unit/test_mcp_project_list_scope.py
git commit -m "refactor(mcp): project_list 가 iter_project_dirs honoring (CLI parity)"
```

---

## Task 9: 전체 게이트 + 죽은 코드 확인 + PR

- [ ] **Step 1: 죽은 helper 잔존 확인**

Run: `grep -rn "_iter_envrcs\|_iter_envrc_files\|_iter_pulumi_yaml\|_iter_git_dirs\|_git_repos_under" src/`
Expected: 정의·참조 모두 없음 (모두 삭제됨). 잔존 시 해당 태스크로 복귀.

- [ ] **Step 2: 전체 단위 테스트**

Run: `.venv/bin/pytest -m "not integration" -q`
Expected: PASS (전체)

- [ ] **Step 3: lint + type**

Run: `.venv/bin/ruff check src/ tests/ && .venv/bin/mypy src/anvyc/ tests/`
Expected: 통과 (미사용 import 잔존 시 ruff F401 → 제거)

- [ ] **Step 4: 실측 doctor 스모크 (개별 프로젝트 honoring 확인)**

Run:
```bash
G=$(mktemp -d); printf 'project_roots: []\nprojects:\n  - %s/dev/anvyc\n' "$HOME" > "$G/anvyc.yaml"
.venv/bin/anvyc doctor --config "$G/anvyc.yaml" --only project-gh-account-mapping 2>&1 | head -20
rm "$G/anvyc.yaml"; rmdir "$G"
```
Expected: `~/dev/anvyc`(개별 project)가 gh-account 체크에 반영됨(이전엔 컨테이너 스캔에만 의존). (※ `--config` 가 doctor 에 없으면 전역 config 임시 편집 대신 이 스텝은 생략하고 unit 테스트로 갈음.)

- [ ] **Step 5: push + PR (self-merge)**

```bash
GIT_SSH_COMMAND='ssh -o IdentityAgent=none -o IdentitiesOnly=yes' git push -u origin feat/consumers-phase2b
gh pr create --base main --fill
gh pr checks --watch
GIT_SSH_COMMAND='ssh -o IdentityAgent=none -o IdentitiesOnly=yes' gh pr merge --squash --delete-branch
```

---

## Self-Review (작성자 점검 완료)

- **스펙 커버리지** (§8 표 8 소비처): unused(T1)·aws(T2)·claude(T3)·pulumi(T4)·gh(T5)·guard(T6)·cursor(T7)·MCP(T8) 전부 태스크 매핑. 각 → `iter_project_dirs(markers, max_depth)`.
- **깊이 보존(P1)**: 5 check = max_depth **2**(=구 _MAX_DEPTH3 marker-parts), guard/cursor = **1**, MCP = **2**. 표로 고정.
- **테스트 호환(P3)**: 각 fixture monkeypatch 를 `anvyc.core.project_roots.{resolve_project_roots,resolve_projects,resolve_excludes}` 로 이전 — lazy import 라 core 패치가 iter_project_dirs 에 반영됨. unused 는 원래 core 패치(deferred)라 호환.
- **helper 삭제 순서(P5)**: unused(T1) 먼저 → aws(T2) `_iter_envrcs` 삭제. `_read_envrc_profile` 보존. T9 Step1 grep 으로 잔존 0 확인.
- **타입/이름 일관성**: 모든 태스크가 `iter_project_dirs(markers=..., max_depth=...)`(Phase 2a 시그니처) 호출. 신규 함수 정의 없음(소비처 내부 교체만).
- **placeholder 없음**: 각 step 에 실제 코드/명령/기대출력. (T4 Step4 doctor `--config` 부재 시 생략 명시 — unit 으로 갈음.)
- **회귀 우선**: 각 태스크가 해당 소비처의 기존 test 파일 전체를 재실행해 동작 보존을 확인한 뒤 projects-honored 신규 테스트로 신규 능력 검증.
