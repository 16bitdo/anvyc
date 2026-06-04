# config roots (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `anvyc config roots <list|add|rm|clear>` 명령으로 컨테이너 프로젝트 root(`project_roots`)를 구조화된 방식으로 입력/수정/제거한다.

**Architecture:** 읽기 SoT(`core/project_roots.py`)는 무변경. 신규 순수 변경 모듈(`core/project_roots_edit.py`)이 anvyc.yaml 의 `project_roots` 키를 materialize→add/remove/clear 한다. 쓰기는 공유 atomic writer(`core/yaml_io.py`) + `.bak` + schema 재검증. CLI 는 기존 `config_app` 하위에 `roots` 서브그룹을 추가하고 전역 `~/.anvyc/anvyc.yaml` 을 기본 대상으로 한다. 소비처(9개)는 `resolve_project_roots` 를 이미 읽으므로 **무변경**.

**Tech Stack:** Python 3.11+, typer(CLI), PyYAML(`safe_load`/`safe_dump`), pytest + `typer.testing.CliRunner`.

**Spec:** `docs/superpowers/specs/2026-06-04-project-roots-management-design.md` (Phase 1 부분)

---

## Branch 설정 (구현 시작 전 1회)

```bash
cd ~/dev/anvyc
git switch main && git pull --ff-only
git switch -c feat/config-roots-phase1
```
> anvyc 는 PR 필수(main 직접 push 차단). 모든 커밋은 이 브랜치에서.

## File Structure

| 파일 | 책임 |
|------|------|
| `src/anvyc/core/yaml_io.py` (신규) | `atomic_write_yaml(data, path)` — tempfile + os.replace 원자적 YAML 쓰기 (공유 헬퍼) |
| `src/anvyc/core/project_roots_edit.py` (신규) | roots 변경 순수 로직 — normalize / materialize / add / remove / clear / list 모델 |
| `src/anvyc/cli.py` (수정) | `config_app` 하위 `roots_app` 4개 명령 + 전역/`--local`/`--config` 대상 해석 |
| `tests/unit/test_project_roots_edit.py` (신규) | core 순수 함수 단위 테스트 |
| `tests/unit/test_config_roots_cli.py` (신규) | CLI 동작 테스트 (CliRunner) |
| `src/anvyc/core/tools_select.py` (수정) | 중복 `_atomic_write_yaml` 제거 → `yaml_io.atomic_write_yaml` 재사용 (DRY) |
| `examples/anvyc.yaml`·`README.md`·`DESIGN.md`·`CONTEXT.md` (수정) | 문서 갱신 |

---

## Task 1: 공유 atomic YAML writer (`core/yaml_io.py`)

**Files:**
- Create: `src/anvyc/core/yaml_io.py`
- Test: `tests/unit/test_yaml_io.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_yaml_io.py
"""core.yaml_io — atomic YAML writer 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import yaml

from anvyc.core.yaml_io import atomic_write_yaml


def test_atomic_write_creates_parent_and_roundtrips(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "anvyc.yaml"
    atomic_write_yaml({"project_roots": ["~/dev", "~/work"]}, target)
    assert target.is_file()
    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert loaded == {"project_roots": ["~/dev", "~/work"]}


def test_atomic_write_overwrites_and_no_tmp_left(tmp_path: Path) -> None:
    target = tmp_path / "anvyc.yaml"
    target.write_text("old: 1\n", encoding="utf-8")
    atomic_write_yaml({"new": 2}, target)
    assert yaml.safe_load(target.read_text()) == {"new": 2}
    # tempfile 잔존 없음 (target 1개만)
    assert [p.name for p in tmp_path.iterdir()] == ["anvyc.yaml"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_yaml_io.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'anvyc.core.yaml_io'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/anvyc/core/yaml_io.py
"""원자적 YAML 쓰기 — tempfile.mkstemp + os.replace.

여러 config 변경 명령(tools_select / project_roots_edit)이 공유한다.
부분 쓰기로 인한 손상 방지: 같은 디렉터리에 임시 파일을 쓴 뒤 os.replace 로 교체.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def atomic_write_yaml(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_yaml_io.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/yaml_io.py tests/unit/test_yaml_io.py
git commit -m "feat(yaml-io): 공유 atomic YAML writer 추출"
```

---

## Task 2: `normalize_root` 정규화

**Files:**
- Create: `src/anvyc/core/project_roots_edit.py`
- Test: `tests/unit/test_project_roots_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_project_roots_edit.py
"""core.project_roots_edit — roots 변경 순수 로직 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core.project_roots_edit import normalize_root


def test_normalize_keeps_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("~/dev") == "~/dev"


def test_normalize_contracts_home_abs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("/Users/tester/work") == "~/work"
    assert normalize_root("/Users/tester") == "~"


def test_normalize_strips_trailing_slash_and_space(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("  ~/dev/  ") == "~/dev"


def test_normalize_keeps_non_home_abs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("/opt/projects") == "/opt/projects"


def test_normalize_empty_returns_empty() -> None:
    assert normalize_root("   ") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'anvyc.core.project_roots_edit'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/anvyc/core/project_roots_edit.py
"""프로젝트 컨테이너 root(`project_roots`) 변경 순수 로직.

읽기 SoT(`project_roots.py`)와 분리. anvyc.yaml 의 `project_roots` 키만 다룬다:
materialize(defaults 구체화) → add/remove/clear. 쓰기는 yaml_io.atomic_write_yaml
+ `.bak` + schema 재검증. `~` 미확장 저장(머신 간 휴대성).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from anvyc.core.project_roots import DEFAULT_PROJECT_ROOTS
from anvyc.core.yaml_io import atomic_write_yaml


def normalize_root(raw: str) -> str:
    """strip → 후행 슬래시 제거 → `$HOME` 하위 절대경로는 `~/..` 로 재축약."""
    s = raw.strip()
    if not s:
        return ""
    if len(s) > 1:
        s = s.rstrip("/")
    home = str(Path.home())
    expanded = str(Path(s).expanduser())
    if expanded == home:
        return "~"
    if expanded.startswith(home + os.sep):
        return "~/" + expanded[len(home) + 1:]
    return s
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_roots_edit.py tests/unit/test_project_roots_edit.py
git commit -m "feat(roots-edit): normalize_root 경로 정규화"
```

---

## Task 3: raw 로드 + materialize (`_load_raw`, `_current_explicit_roots`)

**Files:**
- Modify: `src/anvyc/core/project_roots_edit.py`
- Test: `tests/unit/test_project_roots_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_project_roots_edit.py
from anvyc.core.project_roots_edit import _current_explicit_roots, _load_raw
from anvyc.core.project_roots import DEFAULT_PROJECT_ROOTS


def test_load_raw_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _load_raw(tmp_path / "nope.yaml") == {}


def test_current_roots_explicit(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/work\n  - ~/side\n")
    roots, was_explicit = _current_explicit_roots(_load_raw(cfg))
    assert roots == ["~/work", "~/side"]
    assert was_explicit is True


def test_current_roots_materializes_default(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")  # project_roots 없음
    roots, was_explicit = _current_explicit_roots(_load_raw(cfg))
    assert roots == list(DEFAULT_PROJECT_ROOTS)
    assert was_explicit is False


def test_current_roots_empty_list_materializes(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots: []\n")
    roots, was_explicit = _current_explicit_roots(_load_raw(cfg))
    assert roots == list(DEFAULT_PROJECT_ROOTS)
    assert was_explicit is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "load_raw or current_roots" -v`
Expected: FAIL — `ImportError: cannot import name '_current_explicit_roots'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/anvyc/core/project_roots_edit.py
def _load_raw(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _current_explicit_roots(raw: dict[str, Any]) -> tuple[list[str], bool]:
    """(roots, was_explicit). 명시 비어있으면 DEFAULT 로 materialize."""
    val = raw.get("project_roots")
    if isinstance(val, list):
        cleaned = [str(x).strip() for x in val if str(x).strip()]
        if cleaned:
            return cleaned, True
    return list(DEFAULT_PROJECT_ROOTS), False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "load_raw or current_roots" -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_roots_edit.py tests/unit/test_project_roots_edit.py
git commit -m "feat(roots-edit): raw 로드 + defaults materialize"
```

---

## Task 4: `RootsEditResult` + 공유 writer (`_write_roots`)

**Files:**
- Modify: `src/anvyc/core/project_roots_edit.py`
- Test: `tests/unit/test_project_roots_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_project_roots_edit.py
from anvyc.core.project_roots_edit import _write_roots


def test_write_roots_backup_and_revalidate(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    backup = _write_roots({"project_roots": ["~/dev", "~/work"]}, cfg, make_backup=True)
    assert backup is not None and backup.name == "anvyc.yaml.bak"
    assert "old" not in cfg.read_text()
    import yaml as _y
    assert _y.safe_load(cfg.read_text())["project_roots"] == ["~/dev", "~/work"]


def test_write_roots_restores_on_revalidate_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")

    def _boom(_path: Path) -> object:
        raise ValueError("schema invalid")

    monkeypatch.setattr("anvyc.core.config.load_anvyc_config", _boom)
    with pytest.raises(ValueError):
        _write_roots({"project_roots": ["~/x"]}, cfg, make_backup=True)
    # 원본 복구
    import yaml as _y
    assert _y.safe_load(cfg.read_text())["project_roots"] == ["~/dev"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k write_roots -v`
Expected: FAIL — `ImportError: cannot import name '_write_roots'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/anvyc/core/project_roots_edit.py
@dataclass
class RootsEditResult:
    action: str                                  # "add" | "remove" | "clear"
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)      # 중복(add) / 비목록(remove)
    warnings: list[str] = field(default_factory=list)     # 미존재 dir / 상대경로
    effective_after: list[str] = field(default_factory=list)
    materialized: bool = False
    cleared_to_default: bool = False
    written: bool = False
    config_path: Path | None = None
    backup_path: Path | None = None


def _write_roots(raw: dict[str, Any], config_path: Path, *, make_backup: bool) -> Path | None:
    backup: Path | None = None
    if make_backup and config_path.is_file():
        backup = config_path.with_name(config_path.name + ".bak")
        backup.write_bytes(config_path.read_bytes())
    atomic_write_yaml(raw, config_path)
    from anvyc.core.config import load_anvyc_config

    try:
        load_anvyc_config(config_path)
    except Exception:
        if backup is not None:
            config_path.write_bytes(backup.read_bytes())
        raise
    return backup
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k write_roots -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_roots_edit.py tests/unit/test_project_roots_edit.py
git commit -m "feat(roots-edit): RootsEditResult + 백업·재검증 writer"
```

---

## Task 5: `add_roots`

**Files:**
- Modify: `src/anvyc/core/project_roots_edit.py`
- Test: `tests/unit/test_project_roots_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_project_roots_edit.py
from anvyc.core.project_roots_edit import add_roots
from anvyc.core.project_roots import DEFAULT_PROJECT_ROOTS as _DEF


def test_add_materializes_then_appends(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")  # 명시 없음
    work = tmp_path / "work"; work.mkdir()
    res = add_roots(cfg, [str(work)])
    assert res.materialized is True
    assert res.effective_after == [*list(_DEF), normalize_for(work)]
    import yaml as _y
    assert _y.safe_load(cfg.read_text())["project_roots"][-1] == normalize_for(work)


def test_add_dedupes_existing(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    res = add_roots(cfg, ["~/dev"])
    assert res.added == [] and res.skipped == ["~/dev"]
    assert res.written is False


def test_add_warns_missing_dir_but_adds(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    res = add_roots(cfg, ["~/definitely-not-here-xyz"])
    assert res.added == ["~/definitely-not-here-xyz"]
    assert any("미존재" in w for w in res.warnings)
    assert res.written is True


def normalize_for(p: Path) -> str:
    """테스트 헬퍼 — tmp_path 는 $HOME 밖이므로 절대경로 그대로."""
    from anvyc.core.project_roots_edit import normalize_root
    return normalize_root(str(p))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "add_" -v`
Expected: FAIL — `ImportError: cannot import name 'add_roots'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/anvyc/core/project_roots_edit.py
def add_roots(
    config_path: Path, raw_paths: list[str], *, make_backup: bool = True
) -> RootsEditResult:
    raw = _load_raw(config_path)
    roots, was_explicit = _current_explicit_roots(raw)
    res = RootsEditResult(action="add", materialized=not was_explicit, config_path=config_path)
    for rp in raw_paths:
        norm = normalize_root(rp)
        if not norm:
            continue
        if not norm.startswith(("~", "/")):
            res.warnings.append(f"상대경로(권장 안 함): {norm}")
        if not Path(norm).expanduser().is_dir():
            res.warnings.append(f"미존재 디렉터리: {norm}")
        if norm in roots:
            res.skipped.append(norm)
            continue
        roots.append(norm)
        res.added.append(norm)
    res.effective_after = roots
    if res.added:
        raw["project_roots"] = roots
        res.backup_path = _write_roots(raw, config_path, make_backup=make_backup)
        res.written = True
    return res
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "add_" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_roots_edit.py tests/unit/test_project_roots_edit.py
git commit -m "feat(roots-edit): add_roots (materialize+dedupe+경고)"
```

---

## Task 6: `remove_roots`

**Files:**
- Modify: `src/anvyc/core/project_roots_edit.py`
- Test: `tests/unit/test_project_roots_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_project_roots_edit.py
from anvyc.core.project_roots_edit import remove_roots


def test_remove_existing(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n  - ~/work\n")
    res = remove_roots(cfg, ["~/work"])
    assert res.removed == ["~/work"] and res.written is True
    import yaml as _y
    assert _y.safe_load(cfg.read_text())["project_roots"] == ["~/dev"]


def test_remove_to_empty_clears_key(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    res = remove_roots(cfg, ["~/dev"])
    assert res.cleared_to_default is True
    import yaml as _y
    assert "project_roots" not in (_y.safe_load(cfg.read_text()) or {})


def test_remove_not_in_list_reported(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    res = remove_roots(cfg, ["~/nope"])
    assert res.skipped == ["~/nope"] and res.removed == []
    assert res.written is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "remove_" -v`
Expected: FAIL — `ImportError: cannot import name 'remove_roots'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/anvyc/core/project_roots_edit.py
def remove_roots(
    config_path: Path, raw_paths: list[str], *, make_backup: bool = True
) -> RootsEditResult:
    raw = _load_raw(config_path)
    roots, was_explicit = _current_explicit_roots(raw)
    res = RootsEditResult(action="remove", materialized=not was_explicit, config_path=config_path)
    targets = [normalize_root(rp) for rp in raw_paths if normalize_root(rp)]
    kept: list[str] = []
    for r in roots:
        if r in targets:
            res.removed.append(r)
        else:
            kept.append(r)
    for t in targets:
        if t not in roots:
            res.skipped.append(t)
    res.effective_after = kept
    if res.removed:
        if kept:
            raw["project_roots"] = kept
        else:
            raw.pop("project_roots", None)
            res.cleared_to_default = True
        res.backup_path = _write_roots(raw, config_path, make_backup=make_backup)
        res.written = True
    return res
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "remove_" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_roots_edit.py tests/unit/test_project_roots_edit.py
git commit -m "feat(roots-edit): remove_roots (빈목록→키삭제)"
```

---

## Task 7: `clear_roots`

**Files:**
- Modify: `src/anvyc/core/project_roots_edit.py`
- Test: `tests/unit/test_project_roots_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_project_roots_edit.py
from anvyc.core.project_roots_edit import clear_roots


def test_clear_removes_key(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n  - ~/work\n")
    res = clear_roots(cfg)
    assert res.cleared_to_default is True and res.written is True
    assert res.removed == ["~/dev", "~/work"]
    import yaml as _y
    assert "project_roots" not in (_y.safe_load(cfg.read_text()) or {})


def test_clear_already_default_noop(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    res = clear_roots(cfg)
    assert res.written is False and res.cleared_to_default is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "clear_" -v`
Expected: FAIL — `ImportError: cannot import name 'clear_roots'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/anvyc/core/project_roots_edit.py
def clear_roots(config_path: Path, *, make_backup: bool = True) -> RootsEditResult:
    raw = _load_raw(config_path)
    res = RootsEditResult(action="clear", config_path=config_path)
    roots, was_explicit = _current_explicit_roots(raw)
    res.effective_after = list(DEFAULT_PROJECT_ROOTS)
    if not was_explicit:
        return res  # 이미 default — no-op
    res.removed = roots
    raw.pop("project_roots", None)
    res.cleared_to_default = True
    res.backup_path = _write_roots(raw, config_path, make_backup=make_backup)
    res.written = True
    return res
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "clear_" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_roots_edit.py tests/unit/test_project_roots_edit.py
git commit -m "feat(roots-edit): clear_roots (defaults 복귀)"
```

---

## Task 8: `load_roots_model` (list 모델)

**Files:**
- Modify: `src/anvyc/core/project_roots_edit.py`
- Test: `tests/unit/test_project_roots_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_project_roots_edit.py
from anvyc.core.project_roots_edit import load_roots_model


def test_load_model_explicit_with_existence_and_count(tmp_path: Path) -> None:
    root = tmp_path / "dev"; (root / "proj").mkdir(parents=True)
    (root / "proj" / ".git").mkdir()
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text(f"project_roots:\n  - {root}\n  - ~/nonexistent-xyz\n")
    model = load_roots_model(cfg)
    assert model.explicit is True
    by_path = {e.path: e for e in model.entries}
    dev = by_path[normalize_for(root)]
    assert dev.source == "explicit" and dev.exists is True and dev.projects == 1
    missing = by_path["~/nonexistent-xyz"]
    assert missing.exists is False and missing.projects == 0


def test_load_model_default_source(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    model = load_roots_model(cfg)
    assert model.explicit is False
    assert all(e.source == "default" for e in model.entries)
    assert [e.path for e in model.entries] == list(_DEF)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "load_model" -v`
Expected: FAIL — `ImportError: cannot import name 'load_roots_model'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/anvyc/core/project_roots_edit.py
@dataclass
class RootEntry:
    path: str
    source: str       # "explicit" | "default"
    exists: bool
    projects: int


@dataclass
class RootsModel:
    entries: list[RootEntry]
    explicit: bool
    config_path: Path


def load_roots_model(config_path: Path) -> RootsModel:
    from anvyc.core.project_discovery import discover_projects

    raw = _load_raw(config_path)
    roots, was_explicit = _current_explicit_roots(raw)
    source = "explicit" if was_explicit else "default"
    entries: list[RootEntry] = []
    for r in roots:
        exists = Path(r).expanduser().is_dir()
        count = len(discover_projects([r])) if exists else 0
        entries.append(RootEntry(path=r, source=source, exists=exists, projects=count))
    return RootsModel(entries=entries, explicit=was_explicit, config_path=config_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_project_roots_edit.py -k "load_model" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_roots_edit.py tests/unit/test_project_roots_edit.py
git commit -m "feat(roots-edit): load_roots_model (list 모델)"
```

---

## Task 9: CLI 대상 해석 + `config roots list`

**Files:**
- Modify: `src/anvyc/cli.py` (config_app 정의 근처: ~115행, `_resolve_anvyc_yaml` 근처: ~1440행)
- Test: `tests/unit/test_config_roots_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_roots_cli.py
"""anvyc config roots <verb> CLI 동작 테스트."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def test_roots_list_default_shows_six(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    result = runner.invoke(app, ["config", "roots", "list", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "~/dev" in result.stdout
    assert "default" in result.stdout


def test_roots_list_json(tmp_path: Path) -> None:
    import json
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    result = runner.invoke(app, ["config", "roots", "list", "--config", str(cfg), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["roots"][0]["path"] == "~/dev"
    assert data["roots"][0]["source"] == "explicit"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config_roots_cli.py -k list -v`
Expected: FAIL — `No such command 'roots'` (exit_code != 0)

- [ ] **Step 3: Write minimal implementation**

`src/anvyc/cli.py` 의 `config_app` 정의(약 115행, `app.add_typer(config_app, ...)` 직후)에 서브앱 등록:

```python
roots_app = typer.Typer(name="roots", help="프로젝트 컨테이너 root 조회/관리 (anvyc.yaml project_roots).")
config_app.add_typer(roots_app, name="roots")
```

`_resolve_anvyc_yaml`(약 1440행) 아래에 대상 해석 헬퍼 추가:

```python
def _resolve_roots_target(config: Path | None, local: bool) -> Path:
    """roots 명령 대상 파일. 기본 전역 ~/.anvyc/anvyc.yaml, --local 은 cwd-우선."""
    if config is not None:
        return config
    if local:
        return _resolve_anvyc_yaml(None)
    return Path("~/.anvyc/anvyc.yaml").expanduser()
```

`config_show` 명령(약 1522행) 뒤에 `roots list` 추가:

```python
@roots_app.command("list")
def roots_list(
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    local: bool = typer.Option(False, "--local", help="cwd-우선 해석(기본: 전역)."),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """등록된 컨테이너 root 를 출처/존재/프로젝트 수와 함께 출력."""
    import json as _json

    from rich.markup import escape

    from anvyc.core.project_roots_edit import load_roots_model

    target = _resolve_roots_target(config, local)
    model = load_roots_model(target)
    if json_out:
        payload = {
            "config": str(target),
            "explicit": model.explicit,
            "roots": [
                {"path": e.path, "source": e.source, "exists": e.exists, "projects": e.projects}
                for e in model.entries
            ],
        }
        typer.echo(_json.dumps(payload, ensure_ascii=False))
        return
    console.print(f"[dim]config: {escape(str(target))} ({'explicit' if model.explicit else 'default'})[/]")
    for e in model.entries:
        mark = "✓" if e.exists else "✗"
        console.print(
            f"  {escape(e.path):24} [dim]({e.source})[/]  {mark}  "
            f"[dim]{e.projects} projects[/]",
            soft_wrap=True,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_config_roots_cli.py -k list -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_config_roots_cli.py
git commit -m "feat(cli): config roots list + 대상 해석"
```

---

## Task 10: `config roots add`

**Files:**
- Modify: `src/anvyc/cli.py` (`roots_list` 뒤)
- Test: `tests/unit/test_config_roots_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_config_roots_cli.py
def test_roots_add_writes_global_by_default(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"; (home / ".anvyc").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    work = tmp_path / "work"; work.mkdir()
    result = runner.invoke(app, ["config", "roots", "add", str(work)])
    assert result.exit_code == 0
    import yaml
    written = yaml.safe_load((home / ".anvyc" / "anvyc.yaml").read_text())
    # materialize 된 defaults + 신규 root
    assert "~/dev" in written["project_roots"]
    assert any(str(work) in r or r == "~/work" for r in written["project_roots"])


def test_roots_add_explicit_config(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    work = tmp_path / "w"; work.mkdir()
    result = runner.invoke(app, ["config", "roots", "add", str(work), "--config", str(cfg)])
    assert result.exit_code == 0
    assert "added" in result.stdout.lower() or "추가" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config_roots_cli.py -k add -v`
Expected: FAIL — `No such command 'add'`

- [ ] **Step 3: Write minimal implementation**

```python
# append after roots_list in src/anvyc/cli.py
@roots_app.command("add")
def roots_add(
    paths: list[str] = typer.Argument(..., help="추가할 컨테이너 root(다수 가능)."),
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    local: bool = typer.Option(False, "--local", help="cwd-우선 해석(기본: 전역)."),
) -> None:
    """컨테이너 root 를 추가한다(첫 추가 시 defaults 를 명시 리스트로 구체화)."""
    from rich.markup import escape

    from anvyc.core.project_roots_edit import add_roots

    target = _resolve_roots_target(config, local)
    res = add_roots(target, paths)
    for w in res.warnings:
        console.print(f"[yellow]warning[/] {escape(w)}")
    if res.materialized:
        console.print("[dim]defaults 를 명시 리스트로 구체화함[/]")
    for p in res.added:
        console.print(f"[green]added[/] {escape(p)}")
    for p in res.skipped:
        console.print(f"[dim]skip[/] {escape(p)} (이미 등록됨)")
    if res.written:
        console.print(f"[dim]→ {escape(str(target))}[/]")
    else:
        console.print("[dim]변경 없음[/]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_config_roots_cli.py -k add -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_config_roots_cli.py
git commit -m "feat(cli): config roots add"
```

---

## Task 11: `config roots rm`

**Files:**
- Modify: `src/anvyc/cli.py` (`roots_add` 뒤)
- Test: `tests/unit/test_config_roots_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_config_roots_cli.py
def test_roots_rm_removes(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n  - ~/work\n")
    result = runner.invoke(app, ["config", "roots", "rm", "~/work", "--config", str(cfg)])
    assert result.exit_code == 0
    import yaml
    assert yaml.safe_load(cfg.read_text())["project_roots"] == ["~/dev"]


def test_roots_rm_to_empty_reverts_to_default(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    result = runner.invoke(app, ["config", "roots", "rm", "~/dev", "--config", str(cfg)])
    assert result.exit_code == 0
    import yaml
    assert "project_roots" not in (yaml.safe_load(cfg.read_text()) or {})
    assert "default" in result.stdout.lower() or "복귀" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config_roots_cli.py -k rm -v`
Expected: FAIL — `No such command 'rm'`

- [ ] **Step 3: Write minimal implementation**

```python
# append after roots_add in src/anvyc/cli.py
@roots_app.command("rm")
def roots_rm(
    paths: list[str] = typer.Argument(..., help="제거할 컨테이너 root(다수 가능)."),
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    local: bool = typer.Option(False, "--local", help="cwd-우선 해석(기본: 전역)."),
) -> None:
    """컨테이너 root 를 제거한다(결과가 비면 defaults 로 복귀)."""
    from rich.markup import escape

    from anvyc.core.project_roots_edit import remove_roots

    target = _resolve_roots_target(config, local)
    res = remove_roots(target, paths)
    for p in res.removed:
        console.print(f"[green]removed[/] {escape(p)}")
    for p in res.skipped:
        console.print(f"[yellow]warning[/] {escape(p)} (목록에 없음)")
    if res.cleared_to_default:
        console.print("[dim]명시 리스트 비어 default 로 복귀[/]")
    if res.written:
        console.print(f"[dim]→ {escape(str(target))}[/]")
    elif not res.removed:
        console.print("[dim]변경 없음[/]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_config_roots_cli.py -k rm -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_config_roots_cli.py
git commit -m "feat(cli): config roots rm"
```

---

## Task 12: `config roots clear`

**Files:**
- Modify: `src/anvyc/cli.py` (`roots_rm` 뒤)
- Test: `tests/unit/test_config_roots_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_config_roots_cli.py
def test_roots_clear_reverts(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n  - ~/work\n")
    result = runner.invoke(app, ["config", "roots", "clear", "--config", str(cfg)])
    assert result.exit_code == 0
    import yaml
    assert "project_roots" not in (yaml.safe_load(cfg.read_text()) or {})
    # before→after 출력에 default 표시
    assert "~/dev" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config_roots_cli.py -k clear -v`
Expected: FAIL — `No such command 'clear'`

- [ ] **Step 3: Write minimal implementation**

```python
# append after roots_rm in src/anvyc/cli.py
@roots_app.command("clear")
def roots_clear(
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    local: bool = typer.Option(False, "--local", help="cwd-우선 해석(기본: 전역)."),
) -> None:
    """명시 project_roots 를 모두 제거하고 내장 defaults 로 복귀한다."""
    from rich.markup import escape

    from anvyc.core.project_roots_edit import clear_roots

    target = _resolve_roots_target(config, local)
    res = clear_roots(target)
    if not res.written:
        console.print("[dim]이미 default 사용 중 — 변경 없음[/]")
        return
    console.print(f"[green]cleared[/] {len(res.removed)} explicit root(s)")
    console.print("[dim]default 복귀: " + escape(", ".join(res.effective_after)) + "[/]")
    console.print(f"[dim]→ {escape(str(target))}[/]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_config_roots_cli.py -k clear -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_config_roots_cli.py
git commit -m "feat(cli): config roots clear"
```

---

## Task 13: `tools_select` 를 공유 writer 로 마이그레이션 (DRY)

**Files:**
- Modify: `src/anvyc/core/tools_select.py:216-228` (`_atomic_write_yaml` 정의 + 호출부 212행)

- [ ] **Step 1: 기존 tools_select 테스트로 회귀 가드 확인**

Run: `.venv/bin/pytest tests/unit/test_tools_select.py -v`
Expected: PASS (현재 상태 baseline)

- [ ] **Step 2: 중복 제거 — import 교체**

`src/anvyc/core/tools_select.py` 상단 import 에 추가:
```python
from anvyc.core.yaml_io import atomic_write_yaml
```
212행 호출 교체: `_atomic_write_yaml(raw, config_path)` → `atomic_write_yaml(raw, config_path)`
216-228행의 `def _atomic_write_yaml(...)` 블록과 그에 딸린 미사용 import(`contextlib`, `os`, `tempfile` 가 이 함수 전용이면) 제거. (다른 곳에서 쓰면 유지.)

- [ ] **Step 3: 회귀 테스트 재실행**

Run: `.venv/bin/pytest tests/unit/test_tools_select.py tests/unit/test_yaml_io.py -v`
Expected: PASS (동작 불변)

- [ ] **Step 4: lint/type 확인**

Run: `.venv/bin/ruff check src/ tests/ && .venv/bin/mypy src/anvyc/ tests/`
Expected: 통과 (미사용 import 잔존 시 ruff F401 → 제거)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/tools_select.py
git commit -m "refactor(tools-select): 공유 yaml_io.atomic_write_yaml 재사용"
```

---

## Task 14: 문서 갱신

**Files:**
- Modify: `examples/anvyc.yaml`, `README.md`, `DESIGN.md`, `CONTEXT.md`

- [ ] **Step 1: `examples/anvyc.yaml` 에 top-level project_roots 예시 추가**

파일 상단(다른 top-level 키 근처)에 추가:
```yaml
# 프로젝트 컨테이너 root — anvyc 가 자식을 순회해 프로젝트를 discovery.
# 미설정 시 내장 defaults(~/dev, ~/Projects, ~/code, ~/Code, ~/workspace, ~/src) 사용.
# 관리: anvyc config roots <list|add|rm|clear>
project_roots:
  - ~/dev
```

- [ ] **Step 2: `README.md` 에 사용 예 추가** (config 관련 섹션)

```markdown
### 프로젝트 root 관리

anvyc 가 스캔할 컨테이너 root 를 관리한다(전역 `~/.anvyc/anvyc.yaml`).

```bash
anvyc config roots list              # 현재 root + 출처/존재/프로젝트 수
anvyc config roots add ~/work ~/oss  # 다수 추가(첫 추가 시 defaults 구체화)
anvyc config roots rm ~/oss          # 제거(비면 defaults 복귀)
anvyc config roots clear             # defaults 로 복귀
```
```

- [ ] **Step 3: `DESIGN.md` 의 project_roots SoT 섹션에 관리 명령 추가**

`DEFAULT_PROJECT_ROOTS` 설명 단락 뒤에 한 줄 추가:
```markdown
- 관리 명령: `anvyc config roots <list|add|rm|clear>` (`core/project_roots_edit.py`) —
  전역 `~/.anvyc/anvyc.yaml` 의 `project_roots` 를 materialize 후 편집. 개별 프로젝트
  관리(`config projects`)는 Phase 2(별도 spec/plan).
```

- [ ] **Step 4: `CONTEXT.md` 진행 상태 갱신**

진행 상황 섹션에 항목 추가:
```markdown
- config roots (Phase 1) 구현: `anvyc config roots list/add/rm/clear` — 컨테이너 root CRUD.
  개별 프로젝트(config projects)는 Phase 2 대기.
```

- [ ] **Step 5: Commit**

```bash
git add examples/anvyc.yaml README.md DESIGN.md CONTEXT.md
git commit -m "docs(roots): config roots 사용 예 + project_roots 예시 보강"
```

---

## Task 15: 전체 게이트 + PR

- [ ] **Step 1: 전체 단위 테스트**

Run: `.venv/bin/pytest -m "not integration" -q`
Expected: PASS (전체 통과, 신규 테스트 포함)

- [ ] **Step 2: lint + type**

Run: `.venv/bin/ruff check src/ tests/ && .venv/bin/mypy src/anvyc/ tests/`
Expected: 통과

- [ ] **Step 3: 실측 스모크**

Run:
```bash
.venv/bin/anvyc config roots list --config /tmp/smoke-anvyc.yaml
.venv/bin/anvyc config roots add ~/dev --config /tmp/smoke-anvyc.yaml
.venv/bin/anvyc config roots list --config /tmp/smoke-anvyc.yaml
.venv/bin/anvyc config roots clear --config /tmp/smoke-anvyc.yaml
rm -f /tmp/smoke-anvyc.yaml /tmp/smoke-anvyc.yaml.bak
```
Expected: list→add(materialize)→list(7개)→clear(default 복귀) 정상 출력

- [ ] **Step 4: push + PR (self-merge)**

```bash
git push -u origin feat/config-roots-phase1
gh pr create --base main --fill
gh pr checks --watch
gh pr merge --squash --delete-branch
```

---

## Self-Review (작성자 점검 완료)

- **스펙 커버리지**: §6.1 roots list/add/rm/clear → Task 9-12. §7 materialize/normalize/dedupe → Task 2-7. §3 전역 대상 → Task 9 `_resolve_roots_target`. §3 .bak+atomic+재검증 → Task 1,4. §12 문서 → Task 14. (Phase 2 항목은 본 plan 범위 외 — 별도 plan.)
- **타입 일관성**: `RootsEditResult`(action/added/removed/skipped/warnings/effective_after/materialized/cleared_to_default/written/config_path/backup_path) 는 Task 4 정의 후 5-7 에서 동일 필드 사용. `load_roots_model`→`RootsModel(entries/explicit/config_path)` Task 8 정의·Task 9 소비 일치. `normalize_root`/`add_roots`/`remove_roots`/`clear_roots` 시그니처 Task 간 일치.
- **placeholder 없음**: 모든 step 에 실제 코드/명령/기대출력 포함.
