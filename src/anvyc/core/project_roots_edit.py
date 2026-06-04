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
        # 저장값도 정규화 — hand-edit 된 `~/work/`(후행 슬래시) 등이 rm/dedup 비교와 일치하도록.
        cleaned = [n for n in (normalize_root(str(x)) for x in val) if n]
        if cleaned:
            return cleaned, True
    return list(DEFAULT_PROJECT_ROOTS), False


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
        if norm in roots:           # dedup 먼저 — 중복은 경고 없이 skip
            res.skipped.append(norm)
            continue
        if not norm.startswith(("~", "/")):
            res.warnings.append(f"상대경로(권장 안 함): {norm}")
        if not Path(norm).expanduser().is_dir():
            res.warnings.append(f"미존재 디렉터리: {norm}")
        roots.append(norm)
        res.added.append(norm)
    res.effective_after = roots
    if res.added:
        raw["project_roots"] = roots
        res.backup_path = _write_roots(raw, config_path, make_backup=make_backup)
        res.written = True
    return res


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
