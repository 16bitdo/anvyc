# config projects (Phase 2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 개별 프로젝트 포함/제외(`projects`/`exclude_projects`)를 anvyc.yaml 에서 관리하는 `anvyc config projects <list|add|rm|exclude|unexclude>` 와, 컨테이너∪개별−제외를 합산하는 공유 resolver `iter_project_dirs` 를 추가하고, `anvyc project list` 가 이를 honoring 하도록 통합한다.

**Architecture:** Phase 1(`config roots`) 위에 구축. 신규 `core/project_scope.py` 가 통합 후보 iterator `iter_project_dirs(config, markers, max_depth)` = container-walk ∪ explicit projects − excludes 를 제공한다. `core/project_roots_edit.py` 에 projects/exclude 변경 로직을 추가(roots 와 helper 공유). `config projects` CLI 서브그룹 + project list 통합. **나머지 7개 소비처(guard·5 check·cursor) 리팩터는 Phase 2b(별도 plan)** — 본 plan 은 부가적·저위험(기존 check 동작 무변경).

**Tech Stack:** Python 3.11+, typer, PyYAML, pytest + CliRunner.

**Spec:** `docs/superpowers/specs/2026-06-04-project-roots-management-design.md` (§5 데이터, §6.2 projects 명령, §8 iter_project_dirs)

---

## Branch 설정 (구현 시작 전 1회)

```bash
cd ~/dev/anvyc
git switch main && git pull --ff-only
git switch -c feat/config-projects-phase2a
```
> anvyc 는 PR 필수. SSH agent 이슈 시 push 는 `GIT_SSH_COMMAND='ssh -o IdentityAgent=none -o IdentitiesOnly=yes' git push ...`.

## File Structure

| 파일 | 책임 |
|------|------|
| `src/anvyc/core/config.py` (수정) | `AnvycConfig.projects`/`exclude_projects` 필드 + 파싱 |
| `src/anvyc/core/project_roots.py` (수정) | `resolve_projects`/`resolve_excludes` (resolve_project_roots 미러) |
| `src/anvyc/core/project_scope.py` (신규) | `_has_any_marker`·`_walk_markers`·`iter_project_dirs` — 통합 후보 iterator |
| `src/anvyc/core/project_discovery.py` (수정) | `_walk`/`_has_marker` 를 project_scope 로 이관·위임 (DRY) |
| `src/anvyc/core/project_roots_edit.py` (수정) | projects/exclude 변경 로직 — `_edit_list`·add/remove/exclude/unexclude·load_projects_model (roots helper 재사용) |
| `src/anvyc/cli.py` (수정) | `config projects` 서브그룹 5개 명령 + project list 통합 |
| `tests/unit/test_project_scope.py` (신규) | iter_project_dirs 단위 |
| `tests/unit/test_project_roots_edit.py` (수정) | projects 변경 로직 테스트 추가 |
| `tests/unit/test_config_projects_cli.py` (신규) | CLI 동작 |
| `tests/unit/test_config.py`·`test_project_roots.py`·`test_project_discovery.py` (수정) | 스키마·resolve·discover 회귀 |
| docs (`examples/anvyc.yaml`·README·DESIGN) | projects/exclude 예시·명령 |

---

## Task 1: 스키마 — `AnvycConfig.projects` / `exclude_projects`

**Files:**
- Modify: `src/anvyc/core/config.py:209` (필드), `:377` (파싱)
- Test: `tests/unit/test_config.py` (없으면 생성)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config.py 에 추가 (없으면 헤더 포함 생성)
from pathlib import Path

from anvyc.core.config import AnvycConfig, load_anvyc_config


def test_config_parses_projects_and_excludes(tmp_path: Path) -> None:
    cfg_file = tmp_path / "anvyc.yaml"
    cfg_file.write_text(
        "projects:\n  - ~/work/x\nexclude_projects:\n  - ~/dev/archived\n"
    )
    cfg = load_anvyc_config(cfg_file)
    assert cfg.projects == ["~/work/x"]
    assert cfg.exclude_projects == ["~/dev/archived"]


def test_config_defaults_projects_empty() -> None:
    cfg = AnvycConfig()
    assert cfg.projects == [] and cfg.exclude_projects == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config.py -k "projects" -v`
Expected: FAIL — `AttributeError: 'AnvycConfig' object has no attribute 'projects'`

- [ ] **Step 3: Write minimal implementation**

In `src/anvyc/core/config.py`, after the `project_roots` field (line 209) inside `class AnvycConfig`:
```python
    projects: list[str] = field(default_factory=list)          # 개별 프로젝트 (직접 포함)
    exclude_projects: list[str] = field(default_factory=list)  # 개별 제외
```
In `load_anvyc_config`'s `return AnvycConfig(...)` (near line 377), after `project_roots=list(raw.get("project_roots") or []),`:
```python
        projects=list(raw.get("projects") or []),
        exclude_projects=list(raw.get("exclude_projects") or []),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_config.py -k "projects" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/config.py tests/unit/test_config.py
git commit -m "feat(config): AnvycConfig projects/exclude_projects 스키마"
```

---

## Task 2: `resolve_projects` / `resolve_excludes`

**Files:**
- Modify: `src/anvyc/core/project_roots.py` (resolve_project_roots 뒤)
- Test: `tests/unit/test_project_roots.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_project_roots.py 에 추가
from anvyc.core.project_roots import resolve_excludes, resolve_projects
from anvyc.core.config import AnvycConfig


def test_resolve_projects_reads_config() -> None:
    cfg = AnvycConfig(projects=["~/work/x", "  ~/y  "], exclude_projects=["~/z"])
    assert resolve_projects(cfg) == ("~/work/x", "~/y")
    assert resolve_excludes(cfg) == ("~/z",)


def test_resolve_projects_empty_default() -> None:
    cfg = AnvycConfig()
    assert resolve_projects(cfg) == ()
    assert resolve_excludes(cfg) == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_roots.py -k "resolve_projects or resolve_excludes" -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_projects'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/anvyc/core/project_roots.py`:
```python
def _resolve_list(config: AnvycConfig | None, attr: str) -> tuple[str, ...]:
    cfg = config
    if cfg is None:
        try:
            from anvyc.core.config import load_anvyc_config

            cfg = load_anvyc_config()
        except Exception:
            return ()
    vals = getattr(cfg, attr, None) or []
    return tuple(str(v).strip() for v in vals if str(v).strip())


def resolve_projects(config: AnvycConfig | None = None) -> tuple[str, ...]:
    """anvyc.yaml 의 top-level `projects`(개별 포함). 미설정/실패 시 빈 튜플."""
    return _resolve_list(config, "projects")


def resolve_excludes(config: AnvycConfig | None = None) -> tuple[str, ...]:
    """anvyc.yaml 의 top-level `exclude_projects`(개별 제외). 미설정/실패 시 빈 튜플."""
    return _resolve_list(config, "exclude_projects")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_roots.py -k "resolve_projects or resolve_excludes" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_roots.py tests/unit/test_project_roots.py
git commit -m "feat(project-roots): resolve_projects/resolve_excludes"
```

---

## Task 3: `project_scope` — walk 원시 + project_discovery 위임 (DRY)

**Files:**
- Create: `src/anvyc/core/project_scope.py`
- Modify: `src/anvyc/core/project_discovery.py` (`_has_marker`/`_walk` 제거 → project_scope 위임)
- Test: `tests/unit/test_project_scope.py`, 회귀: `tests/unit/test_project_discovery.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_project_scope.py
"""core.project_scope — walk 원시 단위 테스트."""
from __future__ import annotations

from pathlib import Path

from anvyc.core.project_scope import _has_any_marker, _walk_markers


def test_has_any_marker_file_or_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert _has_any_marker(tmp_path, (".git",)) is True
    assert _has_any_marker(tmp_path, (".envrc",)) is False
    (tmp_path / ".envrc").write_text("")
    assert _has_any_marker(tmp_path, (".envrc",)) is True


def test_walk_markers_depth_and_stop_at_marker(tmp_path: Path) -> None:
    # root/a/.git  (depth1 project)  +  root/b/c/.git (depth2)  + root/d (no marker)
    (tmp_path / "a" / ".git").mkdir(parents=True)
    (tmp_path / "b" / "c" / ".git").mkdir(parents=True)
    (tmp_path / "d").mkdir()
    found: set[Path] = set()
    _walk_markers(tmp_path, depth=1, max_depth=2, markers=(".git",), found=found)
    names = {p.name for p in found}
    assert names == {"a", "c"}  # a(depth1), c(depth2); d 없음
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_scope.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'anvyc.core.project_scope'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/anvyc/core/project_scope.py
"""프로젝트 스캔 통합 — 컨테이너 root walk ∪ 개별 projects − exclude_projects.

모든 "프로젝트 디렉터리 스캔" 소비처가 공유할 후보 iterator. marker(파일 또는
디렉터리) 보유 디렉터리를 수집한다. walk 원시(`_walk_markers`)는 project_discovery
가 위임해 단일화한다.
"""
from __future__ import annotations

from pathlib import Path


def _has_any_marker(path: Path, markers: tuple[str, ...]) -> bool:
    return any((path / m).exists() for m in markers)


def _walk_markers(
    directory: Path, *, depth: int, max_depth: int, markers: tuple[str, ...], found: set[Path]
) -> None:
    """directory 아래 markers 보유 디렉터리를 found 에 수집(marker 발견 시 미하강)."""
    if depth > max_depth:
        return
    try:
        entries = list(directory.iterdir())
    except (OSError, PermissionError):
        return
    for entry in entries:
        if not entry.is_dir() or entry.is_symlink():
            continue
        try:
            resolved = entry.resolve()
        except OSError:
            continue
        if _has_any_marker(entry, markers):
            found.add(resolved)
            continue
        if depth < max_depth:
            _walk_markers(
                entry, depth=depth + 1, max_depth=max_depth, markers=markers, found=found
            )
```

> `iter_project_dirs` 는 Task 4 에서 추가한다(본 태스크는 walk 원시 + discover 위임까지). project_scope.py 상단 docstring 의 "후보 iterator" 언급은 Task 4 구현 전제로 둔다.

Then refactor `src/anvyc/core/project_discovery.py` to delegate the walk (remove its own `_has_marker` and `_walk`, keep `PROJECT_MARKERS`/`DEFAULT_MAX_DEPTH`/`discover_projects`):
```python
from anvyc.core.project_scope import _walk_markers
# ... keep PROJECT_MARKERS, DEFAULT_MAX_DEPTH ...
# inside discover_projects, replace the `_walk(root, ...)` call with:
        _walk_markers(root, depth=1, max_depth=max_depth, markers=PROJECT_MARKERS, found=found)
# delete the old module-level `_has_marker` and `_walk` definitions.
```

- [ ] **Step 4: Run test to verify it passes (+ discover regression)**

Run: `.venv/bin/pytest tests/unit/test_project_scope.py tests/unit/test_project_discovery.py -v`
Expected: PASS (project_scope new + discover_projects unchanged behavior)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_scope.py src/anvyc/core/project_discovery.py tests/unit/test_project_scope.py
git commit -m "feat(project-scope): walk 원시 단일화 + discover_projects 위임"
```

---

## Task 4: `iter_project_dirs` — container ∪ projects − excludes

**Files:**
- Modify: `src/anvyc/core/project_scope.py` (Task 3 파일에 `iter_project_dirs` 추가)
- Test: `tests/unit/test_project_scope.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_project_scope.py 에 추가 (import 는 파일 상단으로 합칠 것 — ruff E402)
from anvyc.core.config import AnvycConfig
from anvyc.core.project_scope import iter_project_dirs


def test_iter_union_projects_minus_excludes(tmp_path: Path) -> None:
    container = tmp_path / "dev"
    (container / "p1" / ".git").mkdir(parents=True)
    (container / "p2" / ".git").mkdir(parents=True)
    indiv = tmp_path / "work" / "x"
    (indiv / ".git").mkdir(parents=True)
    cfg = AnvycConfig(
        project_roots=[str(container)],
        projects=[str(indiv)],
        exclude_projects=[str(container / "p2")],
    )
    dirs = iter_project_dirs(cfg, markers=(".git",), max_depth=2)
    names = sorted(p.name for p in dirs)
    assert names == ["p1", "x"]  # p1(container) + x(individual) − p2(excluded)


def test_iter_individual_without_marker_skipped(tmp_path: Path) -> None:
    indiv = tmp_path / "no-marker"
    indiv.mkdir()
    cfg = AnvycConfig(project_roots=[], projects=[str(indiv)])
    assert iter_project_dirs(cfg, markers=(".git",)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_scope.py -k "iter_" -v`
Expected: FAIL — `ImportError: cannot import name 'iter_project_dirs' from 'anvyc.core.project_scope'`

- [ ] **Step 3: Write minimal implementation**

Add the iter_project_dirs imports to the top of `src/anvyc/core/project_scope.py`:
```python
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anvyc.core.config import AnvycConfig
```
Append the function:
```python
def iter_project_dirs(
    config: "AnvycConfig | None" = None,
    *,
    markers: Iterable[str],
    max_depth: int = 2,
) -> list[Path]:
    """컨테이너(project_roots) walk ∪ 개별(projects, marker 보유) − exclude_projects.

    각 dir 는 markers 중 하나 이상을(파일/디렉터리) 보유. resolve 기준 dedup·정렬.
    """
    from anvyc.core.config import load_anvyc_config
    from anvyc.core.project_roots import (
        resolve_excludes,
        resolve_project_roots,
        resolve_projects,
    )

    cfg = config if config is not None else load_anvyc_config()
    marker_t = tuple(markers)
    found: set[Path] = set()
    for root_str in resolve_project_roots(cfg):
        root = Path(root_str).expanduser()
        if root.is_dir():
            _walk_markers(root, depth=1, max_depth=max_depth, markers=marker_t, found=found)
    for p_str in resolve_projects(cfg):
        p = Path(p_str).expanduser()
        if p.is_dir() and _has_any_marker(p, marker_t):
            try:
                found.add(p.resolve())
            except OSError:
                continue
    for e_str in resolve_excludes(cfg):
        try:
            found.discard(Path(e_str).expanduser().resolve())
        except OSError:
            continue
    return sorted(found, key=lambda p: str(p))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_scope.py -v`
Expected: PASS (전체)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_scope.py tests/unit/test_project_scope.py
git commit -m "feat(project-scope): iter_project_dirs (container ∪ projects − excludes)"
```

---

## Task 5: projects 변경 로직 — `ProjectsEditResult` + `_edit_list` + add/remove

**Files:**
- Modify: `src/anvyc/core/project_roots_edit.py` (끝에 추가 — normalize_root/_load_raw/_write_roots 재사용)
- Test: `tests/unit/test_project_roots_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_project_roots_edit.py 에 추가
from anvyc.core.project_roots_edit import add_projects, remove_projects


def test_add_projects_with_marker(tmp_path: Path) -> None:
    proj = tmp_path / "x"
    (proj / ".git").mkdir(parents=True)
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    res = add_projects(cfg, [str(proj)])
    assert res.added == [normalize_for(proj)] and res.written is True
    import yaml as _y
    assert _y.safe_load(cfg.read_text())["projects"] == [normalize_for(proj)]


def test_add_projects_warns_no_marker_but_adds(tmp_path: Path) -> None:
    proj = tmp_path / "nomarker"
    proj.mkdir()
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    res = add_projects(cfg, [str(proj)])
    assert res.added == [normalize_for(proj)]
    assert any("마커" in w for w in res.warnings)


def test_remove_projects_to_empty_drops_key(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("projects:\n  - ~/work/x\n")
    res = remove_projects(cfg, ["~/work/x"])
    assert res.removed == ["~/work/x"]
    import yaml as _y
    assert "projects" not in (_y.safe_load(cfg.read_text()) or {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "add_projects or remove_projects" -v`
Expected: FAIL — `ImportError: cannot import name 'add_projects'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/anvyc/core/project_roots_edit.py`:
```python
def _has_project_marker(path: Path) -> bool:
    from anvyc.core.project_discovery import PROJECT_MARKERS

    return any((path / m).exists() for m in PROJECT_MARKERS)


def _current_list(raw: dict[str, Any], key: str) -> list[str]:
    val = raw.get(key)
    if isinstance(val, list):
        return [n for n in (normalize_root(str(x)) for x in val) if n]
    return []


@dataclass
class ProjectsEditResult:
    action: str                                  # "add"|"remove"|"exclude"|"unexclude"
    key: str                                     # "projects"|"exclude_projects"
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    effective_after: list[str] = field(default_factory=list)
    written: bool = False
    config_path: Path | None = None
    backup_path: Path | None = None


def _edit_list(
    config_path: Path,
    key: str,
    raw_paths: list[str],
    *,
    op: str,
    action: str,
    require_marker: bool,
    make_backup: bool,
) -> ProjectsEditResult:
    raw = _load_raw(config_path)
    cur = _current_list(raw, key)
    res = ProjectsEditResult(action=action, key=key, config_path=config_path)
    if op == "add":
        other_key = "exclude_projects" if key == "projects" else "projects"
        other = _current_list(raw, other_key)
        for rp in raw_paths:
            norm = normalize_root(rp)
            if not norm:
                continue
            if norm in cur:
                res.skipped.append(norm)
                continue
            p = Path(norm).expanduser()
            if not norm.startswith(("~", "/")):
                res.warnings.append(f"상대경로(권장 안 함): {norm}")
            if not p.is_dir():
                res.warnings.append(f"미존재 디렉터리: {norm}")
            elif require_marker and not _has_project_marker(p):
                res.warnings.append(f"프로젝트 마커(.git/Pulumi.yaml) 없음: {norm}")
            if norm in other:
                res.warnings.append(f"{other_key} 에도 존재 — exclude 우선: {norm}")
            cur.append(norm)
            res.added.append(norm)
    else:  # remove
        targets = [normalize_root(rp) for rp in raw_paths if normalize_root(rp)]
        kept: list[str] = []
        for r in cur:
            (res.removed if r in targets else kept).append(r)
        for t in targets:
            if t not in cur:
                res.skipped.append(t)
        cur = kept
    res.effective_after = cur
    if res.added or res.removed:
        if cur:
            raw[key] = cur
        else:
            raw.pop(key, None)
        res.backup_path = _write_roots(raw, config_path, make_backup=make_backup)
        res.written = True
    return res


def add_projects(
    config_path: Path, raw_paths: list[str], *, make_backup: bool = True
) -> ProjectsEditResult:
    return _edit_list(
        config_path, "projects", raw_paths,
        op="add", action="add", require_marker=True, make_backup=make_backup,
    )


def remove_projects(
    config_path: Path, raw_paths: list[str], *, make_backup: bool = True
) -> ProjectsEditResult:
    return _edit_list(
        config_path, "projects", raw_paths,
        op="remove", action="remove", require_marker=False, make_backup=make_backup,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "add_projects or remove_projects" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_roots_edit.py tests/unit/test_project_roots_edit.py
git commit -m "feat(roots-edit): add_projects/remove_projects (+_edit_list)"
```

---

## Task 6: exclude/unexclude + `load_projects_model`

**Files:**
- Modify: `src/anvyc/core/project_roots_edit.py`
- Test: `tests/unit/test_project_roots_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_project_roots_edit.py 에 추가
from anvyc.core.project_roots_edit import (
    exclude_project,
    load_projects_model,
    unexclude_project,
)


def test_exclude_and_unexclude(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    res = exclude_project(cfg, ["~/dev/archived"])
    assert res.key == "exclude_projects" and res.added == ["~/dev/archived"]
    import yaml as _y
    assert _y.safe_load(cfg.read_text())["exclude_projects"] == ["~/dev/archived"]
    res2 = unexclude_project(cfg, ["~/dev/archived"])
    assert res2.removed == ["~/dev/archived"]
    assert "exclude_projects" not in (_y.safe_load(cfg.read_text()) or {})


def test_add_project_in_exclude_warns_conflict(tmp_path: Path) -> None:
    proj = tmp_path / "x"
    (proj / ".git").mkdir(parents=True)
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text(f"exclude_projects:\n  - {proj}\n")
    res = add_projects(cfg, [str(proj)])
    assert any("exclude 우선" in w for w in res.warnings)


def test_load_projects_model(tmp_path: Path) -> None:
    proj = tmp_path / "x"
    (proj / ".git").mkdir(parents=True)
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text(f"projects:\n  - {proj}\nexclude_projects:\n  - ~/dev/gone\n")
    model = load_projects_model(cfg)
    inc = model.includes[0]
    assert inc.kind == "include" and inc.exists is True and inc.has_marker is True
    exc = model.excludes[0]
    assert exc.kind == "exclude" and exc.exists is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "exclude or load_projects_model" -v`
Expected: FAIL — `ImportError: cannot import name 'exclude_project'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/anvyc/core/project_roots_edit.py`:
```python
def exclude_project(
    config_path: Path, raw_paths: list[str], *, make_backup: bool = True
) -> ProjectsEditResult:
    return _edit_list(
        config_path, "exclude_projects", raw_paths,
        op="add", action="exclude", require_marker=False, make_backup=make_backup,
    )


def unexclude_project(
    config_path: Path, raw_paths: list[str], *, make_backup: bool = True
) -> ProjectsEditResult:
    return _edit_list(
        config_path, "exclude_projects", raw_paths,
        op="remove", action="unexclude", require_marker=False, make_backup=make_backup,
    )


@dataclass
class ProjectEntry:
    path: str
    kind: str        # "include" | "exclude"
    exists: bool
    has_marker: bool


@dataclass
class ProjectsModel:
    includes: list[ProjectEntry]
    excludes: list[ProjectEntry]
    config_path: Path


def load_projects_model(config_path: Path) -> ProjectsModel:
    raw = _load_raw(config_path)

    def _entries(key: str, kind: str) -> list[ProjectEntry]:
        out: list[ProjectEntry] = []
        for p in _current_list(raw, key):
            pp = Path(p).expanduser()
            exists = pp.is_dir()
            out.append(
                ProjectEntry(
                    path=p, kind=kind, exists=exists,
                    has_marker=exists and _has_project_marker(pp),
                )
            )
        return out

    return ProjectsModel(
        includes=_entries("projects", "include"),
        excludes=_entries("exclude_projects", "exclude"),
        config_path=config_path,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "exclude or load_projects_model or conflict" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_roots_edit.py tests/unit/test_project_roots_edit.py
git commit -m "feat(roots-edit): exclude/unexclude + load_projects_model"
```

---

## Task 7: CLI `config projects list`

**Files:**
- Modify: `src/anvyc/cli.py` (config_app 근처 projects_app 등록 + roots 명령 뒤 projects_list)
- Test: `tests/unit/test_config_projects_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_projects_cli.py
"""anvyc config projects <verb> CLI 동작 테스트."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def test_projects_list_json(tmp_path: Path) -> None:
    proj = tmp_path / "x"
    (proj / ".git").mkdir(parents=True)
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text(f"projects:\n  - {proj}\nexclude_projects:\n  - ~/dev/gone\n")
    result = runner.invoke(
        app, ["config", "projects", "list", "--config", str(cfg), "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["includes"][0]["exists"] is True
    assert data["excludes"][0]["path"] == "~/dev/gone"


def test_projects_list_empty(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    result = runner.invoke(app, ["config", "projects", "list", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "없음" in result.stdout or "없습니다" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config_projects_cli.py -k list -v`
Expected: FAIL — `No such command 'projects'`

- [ ] **Step 3: Write minimal implementation**

In `src/anvyc/cli.py`, right after the `config_app.add_typer(roots_app, name="roots")` line (Phase 1), add:
```python
projects_app = typer.Typer(name="projects", help="개별 프로젝트 포함/제외 관리 (anvyc.yaml projects/exclude_projects).")
config_app.add_typer(projects_app, name="projects")
```
After the `roots_clear` command, add:
```python
@projects_app.command("list")
def projects_list(
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    local: bool = typer.Option(False, "--local", help="cwd-우선 해석(기본: 전역)."),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """개별 포함(projects) + 제외(exclude_projects) 를 존재/마커와 함께 출력."""
    import json as _json

    from rich.markup import escape

    from anvyc.core.project_roots_edit import load_projects_model

    target = _resolve_roots_target(config, local)
    model = load_projects_model(target)
    if json_out:
        payload = {
            "config": str(target),
            "includes": [
                {"path": e.path, "exists": e.exists, "has_marker": e.has_marker}
                for e in model.includes
            ],
            "excludes": [
                {"path": e.path, "exists": e.exists} for e in model.excludes
            ],
        }
        typer.echo(_json.dumps(payload, ensure_ascii=False))
        return
    if not model.includes and not model.excludes:
        console.print("[dim]등록된 개별 프로젝트 없음 (config roots 의 컨테이너만 사용 중)[/]")
        return
    console.print(f"[dim]config: {escape(str(target))}[/]")
    for e in model.includes:
        mark = "✓" if e.exists else "✗"
        warn = "" if e.has_marker else " [yellow](마커 없음)[/]"
        console.print(f"  [green]+[/] {escape(e.path):28} {mark}{warn}", soft_wrap=True)
    for e in model.excludes:
        mark = "✓" if e.exists else "✗"
        console.print(f"  [red]-[/] {escape(e.path):28} {mark} [dim](exclude)[/]", soft_wrap=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_config_projects_cli.py -k list -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_config_projects_cli.py
git commit -m "feat(cli): config projects list"
```

---

## Task 8: CLI `config projects add` / `rm`

**Files:**
- Modify: `src/anvyc/cli.py` (`projects_list` 뒤)
- Test: `tests/unit/test_config_projects_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_projects_cli.py 에 추가
import yaml


def test_projects_add_and_rm(tmp_path: Path) -> None:
    proj = tmp_path / "x"
    (proj / ".git").mkdir(parents=True)
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    r1 = runner.invoke(app, ["config", "projects", "add", str(proj), "--config", str(cfg)])
    assert r1.exit_code == 0
    assert "added" in r1.stdout.lower() or "추가" in r1.stdout
    written = yaml.safe_load(cfg.read_text())["projects"]
    assert any(str(proj) in w or w.startswith("~") for w in written)
    r2 = runner.invoke(app, ["config", "projects", "rm", str(proj), "--config", str(cfg)])
    assert r2.exit_code == 0
    assert "projects" not in (yaml.safe_load(cfg.read_text()) or {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config_projects_cli.py -k add_and_rm -v`
Expected: FAIL — `No such command 'add'`

- [ ] **Step 3: Write minimal implementation**

After `projects_list` in `src/anvyc/cli.py`:
```python
def _print_projects_result(res: object, target: Path) -> None:
    from rich.markup import escape

    for w in res.warnings:  # type: ignore[attr-defined]
        console.print(f"[yellow]warning[/] {escape(w)}")
    for p in res.added:  # type: ignore[attr-defined]
        console.print(f"[green]added[/] {escape(p)}")
    for p in res.removed:  # type: ignore[attr-defined]
        console.print(f"[green]removed[/] {escape(p)}")
    for p in res.skipped:  # type: ignore[attr-defined]
        console.print(f"[dim]skip[/] {escape(p)}")
    if res.written:  # type: ignore[attr-defined]
        console.print(f"[dim]→ {escape(str(target))}[/]")
    else:
        console.print("[dim]변경 없음[/]")


@projects_app.command("add")
def projects_add(
    paths: list[str] = typer.Argument(..., help="추가할 개별 프로젝트(다수 가능)."),
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    local: bool = typer.Option(False, "--local", help="cwd-우선 해석(기본: 전역)."),
) -> None:
    """개별 프로젝트를 포함 목록에 추가한다(마커 없으면 경고)."""
    from anvyc.core.project_roots_edit import add_projects

    target = _resolve_roots_target(config, local)
    _print_projects_result(add_projects(target, paths), target)


@projects_app.command("rm")
def projects_rm(
    paths: list[str] = typer.Argument(..., help="포함 목록에서 제거할 프로젝트(다수 가능)."),
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    local: bool = typer.Option(False, "--local", help="cwd-우선 해석(기본: 전역)."),
) -> None:
    """개별 프로젝트를 포함 목록에서 제거한다."""
    from anvyc.core.project_roots_edit import remove_projects

    target = _resolve_roots_target(config, local)
    _print_projects_result(remove_projects(target, paths), target)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_config_projects_cli.py -k add_and_rm -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_config_projects_cli.py
git commit -m "feat(cli): config projects add/rm"
```

---

## Task 9: CLI `config projects exclude` / `unexclude`

**Files:**
- Modify: `src/anvyc/cli.py` (`projects_rm` 뒤)
- Test: `tests/unit/test_config_projects_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_projects_cli.py 에 추가
def test_projects_exclude_and_unexclude(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    r1 = runner.invoke(app, ["config", "projects", "exclude", "~/dev/archived", "--config", str(cfg)])
    assert r1.exit_code == 0
    assert yaml.safe_load(cfg.read_text())["exclude_projects"] == ["~/dev/archived"]
    r2 = runner.invoke(app, ["config", "projects", "unexclude", "~/dev/archived", "--config", str(cfg)])
    assert r2.exit_code == 0
    assert "exclude_projects" not in (yaml.safe_load(cfg.read_text()) or {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config_projects_cli.py -k exclude_and_unexclude -v`
Expected: FAIL — `No such command 'exclude'`

- [ ] **Step 3: Write minimal implementation**

After `projects_rm` in `src/anvyc/cli.py`:
```python
@projects_app.command("exclude")
def projects_exclude(
    paths: list[str] = typer.Argument(..., help="모든 스캔에서 제외할 프로젝트(다수 가능)."),
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    local: bool = typer.Option(False, "--local", help="cwd-우선 해석(기본: 전역)."),
) -> None:
    """개별 프로젝트를 제외 목록(exclude_projects)에 추가한다."""
    from anvyc.core.project_roots_edit import exclude_project

    target = _resolve_roots_target(config, local)
    _print_projects_result(exclude_project(target, paths), target)


@projects_app.command("unexclude")
def projects_unexclude(
    paths: list[str] = typer.Argument(..., help="제외 목록에서 해제할 프로젝트(다수 가능)."),
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    local: bool = typer.Option(False, "--local", help="cwd-우선 해석(기본: 전역)."),
) -> None:
    """개별 프로젝트를 제외 목록에서 해제한다."""
    from anvyc.core.project_roots_edit import unexclude_project

    target = _resolve_roots_target(config, local)
    _print_projects_result(unexclude_project(target, paths), target)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_config_projects_cli.py -k exclude_and_unexclude -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_config_projects_cli.py
git commit -m "feat(cli): config projects exclude/unexclude"
```

---

## Task 10: `project list` 통합 — projects/excludes honoring

**Files:**
- Modify: `src/anvyc/cli.py:2073-2078` (project_list)
- Test: `tests/unit/test_project_list_scope.py` (신규)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_project_list_scope.py
"""anvyc project list 가 projects/exclude_projects 를 honoring 하는지."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def test_project_list_honors_projects_and_excludes(tmp_path: Path, monkeypatch) -> None:
    container = tmp_path / "dev"
    (container / "p1" / ".git").mkdir(parents=True)
    (container / "p2" / ".git").mkdir(parents=True)
    indiv = tmp_path / "work" / "x"
    (indiv / ".git").mkdir(parents=True)
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text(
        f"project_roots:\n  - {container}\nprojects:\n  - {indiv}\n"
        f"exclude_projects:\n  - {container / 'p2'}\n"
    )
    # project list 는 전역 config 를 load — HOME 을 tmp 로 돌려 이 cfg 가 잡히게
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".anvyc").mkdir()
    (tmp_path / ".anvyc" / "anvyc.yaml").write_text(cfg.read_text())
    result = runner.invoke(app, ["project", "list", "--json"])
    assert result.exit_code == 0
    paths = {Path(e["path"]).name for e in json.loads(result.stdout)}
    assert "p1" in paths and "x" in paths and "p2" not in paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_list_scope.py -v`
Expected: FAIL — `p2` still present (project list 이 exclude 미반영) / `x` 없음 (개별 미반영)

- [ ] **Step 3: Write minimal implementation**

In `src/anvyc/cli.py` `project_list`, replace lines 2073-2078:
```python
    from anvyc.core.project_discovery import PROJECT_MARKERS, discover_projects
    from anvyc.core.project_info import collect_project_info, to_dict
    from anvyc.core.project_roots import resolve_project_roots
    from anvyc.core.project_scope import iter_project_dirs

    if roots:
        roots_arg = list(roots)
        projects = discover_projects(roots_arg)  # 명시 --root: 개별/제외 미적용(명시 override)
    else:
        roots_arg = list(resolve_project_roots())
        projects = iter_project_dirs(
            markers=PROJECT_MARKERS, max_depth=2
        )  # 무인자: projects/excludes honoring
```
(아래 `infos`/`payload`/메시지의 `roots_arg` 참조는 그대로 유지.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_list_scope.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_project_list_scope.py
git commit -m "feat(cli): project list 가 projects/exclude_projects honoring (iter_project_dirs)"
```

---

## Task 11: 문서 갱신

**Files:**
- Modify: `examples/anvyc.yaml`, `README.md`, `DESIGN.md`

- [ ] **Step 1: `examples/anvyc.yaml` — project_roots 블록 뒤에 추가**

`project_roots:` 블록 다음에:
```yaml
# 개별 프로젝트 — 컨테이너(project_roots) 밖이라도 직접 포함. 관리: anvyc config projects add/rm
projects: []
# 개별 제외 — 모든 discovery/체크에서 스킵. 관리: anvyc config projects exclude/unexclude
exclude_projects: []
```

- [ ] **Step 2: `README.md` §8 — config roots 줄 뒤에 추가**

```markdown
anvyc config projects {list|add|rm|exclude|unexclude}   # 개별 프로젝트 포함/제외 관리 (anvyc.yaml projects/exclude_projects)
```

- [ ] **Step 3: `DESIGN.md` — project_roots SoT 단락에 추가**

`config roots` 관리 명령 bullet 뒤에:
```markdown
- 개별 프로젝트: `anvyc config projects <list|add|rm|exclude|unexclude>` — `projects`(포함)/
  `exclude_projects`(제외). 통합 resolver `core/project_scope.py iter_project_dirs(markers, max_depth)`
  = 컨테이너 walk ∪ projects − excludes. v0.x: `project list` 가 honoring. 나머지 소비처(doctor
  5 check·guard·cursor-suggest)는 Phase 2b.
```
또한 상단 frontmatter `> 개정일:` 를 `2026-06-04 (config projects Phase 2a 추가)` 로 갱신.

- [ ] **Step 4: 검증 (파싱)**

Run: `.venv/bin/python -c "import yaml; yaml.safe_load(open('examples/anvyc.yaml')); print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add examples/anvyc.yaml README.md DESIGN.md
git commit -m "docs(projects): config projects 사용 예 + projects/exclude_projects 예시"
```

---

## Task 12: 전체 게이트 + PR

- [ ] **Step 1: 전체 단위 테스트**

Run: `.venv/bin/pytest -m "not integration" -q`
Expected: PASS (전체)

- [ ] **Step 2: lint + type**

Run: `.venv/bin/ruff check src/ tests/ && .venv/bin/mypy src/anvyc/ tests/`
Expected: 통과

- [ ] **Step 3: 실측 스모크**

Run:
```bash
S=/tmp/proj-smoke.yaml; printf 'storage:\n  root: .anvyc\n' > "$S"
mkdir -p /tmp/pj/.git
.venv/bin/anvyc config projects add /tmp/pj --config "$S"
.venv/bin/anvyc config projects exclude ~/dev/old --config "$S"
.venv/bin/anvyc config projects list --config "$S"
.venv/bin/anvyc config projects unexclude ~/dev/old --config "$S"
rm -rf "$S" "$S.bak" /tmp/pj
```
Expected: add(+마커 OK)→exclude→list(+1/-1)→unexclude 정상

- [ ] **Step 4: push + PR (self-merge)**

```bash
GIT_SSH_COMMAND='ssh -o IdentityAgent=none -o IdentitiesOnly=yes' git push -u origin feat/config-projects-phase2a
gh pr create --base main --fill
gh pr checks --watch
GIT_SSH_COMMAND='ssh -o IdentityAgent=none -o IdentitiesOnly=yes' gh pr merge --squash --delete-branch
```

---

## Self-Review (작성자 점검 완료)

- **스펙 커버리지**: §5 스키마 → Task 1. §6.2 projects list/add/rm/exclude/unexclude → Task 7-9. §8 iter_project_dirs(컨테이너∪개별−제외) → Task 3-4. resolve_projects/excludes → Task 2. project list honoring → Task 10. (나머지 7개 소비처 통합 = Phase 2b, 본 plan 범위 명시 제외.)
- **타입 일관성**: `ProjectsEditResult`(action/key/added/removed/skipped/warnings/effective_after/written/config_path/backup_path) Task 5 정의 → Task 6·8·9 사용. `ProjectEntry`(path/kind/exists/has_marker)·`ProjectsModel`(includes/excludes/config_path) Task 6 정의 → Task 7 소비. `iter_project_dirs(config, *, markers, max_depth)`·`_walk_markers`·`_has_any_marker` Task 3 정의 → Task 4·10 사용. `resolve_projects`/`resolve_excludes` Task 2 → Task 3 사용. `add_projects`/`remove_projects`/`exclude_project`/`unexclude_project`/`load_projects_model` 시그니처 Task 간 일치. `_resolve_roots_target`(Phase 1)·`normalize_root`/`_load_raw`/`_write_roots`(Phase 1) 재사용.
- **placeholder 없음**: 모든 step 에 실제 코드/명령/기대출력.
- **Phase 2b 명시**: guard_targets·project_gh/aws/claude/pulumi·unused_aws·cursor_projects_suggest 8개 소비처를 iter_project_dirs 로 전환(각 회귀 테스트) — 별도 plan.
