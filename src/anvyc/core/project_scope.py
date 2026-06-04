"""프로젝트 스캔 통합 — 컨테이너 root walk ∪ 개별 projects − exclude_projects.

모든 "프로젝트 디렉터리 스캔" 소비처가 공유할 후보 iterator. marker(파일 또는
디렉터리) 보유 디렉터리를 수집한다. walk 원시(`_walk_markers`)는 project_discovery
가 위임해 단일화한다.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anvyc.core.config import AnvycConfig


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


def iter_project_dirs(
    config: AnvycConfig | None = None,
    *,
    markers: Iterable[str],
    max_depth: int = 2,
) -> list[Path]:
    """컨테이너(project_roots) walk ∪ 개별(projects, marker 보유) − exclude_projects.

    각 dir 는 markers 중 하나 이상을(파일/디렉터리) 보유. resolve 기준 dedup·정렬.
    config 가 None 이면 load_anvyc_config() 후 resolve_project_roots (DEFAULT fallback 포함).
    config 가 명시 제공되면 config.project_roots 를 직접 사용(빈 리스트 = 컨테이너 없음).
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
    # config 명시 제공 시: project_roots 직접 사용(빈 리스트 허용 — DEFAULT fallback 없음)
    # config 가 None 이어서 load 한 경우: resolve_project_roots(DEFAULT fallback 포함)
    if config is not None:
        roots_iter: Iterable[str] = getattr(cfg, "project_roots", None) or []
    else:
        roots_iter = resolve_project_roots(cfg)
    for root_str in roots_iter:
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
