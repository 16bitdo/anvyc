"""프로젝트 스캔 통합 — 컨테이너 root walk ∪ 개별 projects − exclude_projects.

모든 "프로젝트 디렉터리 스캔" 소비처가 공유할 후보 iterator. marker(파일 또는
디렉터리) 보유 디렉터리를 수집한다. walk 원시(`_walk_markers`)는 project_discovery
가 위임해 단일화한다.

Public API:
    iter_project_dirs — 컨테이너(project_roots) walk ∪ 개별(projects) − excludes
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anvyc.core.config import AnvycConfig

__all__ = ["iter_project_dirs"]


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
    project_roots 는 항상 `resolve_project_roots` 를 거친다 — 빈 리스트면 DEFAULT
    fallback (config 인자 유무와 무관한 일관 계약; 소비처가 의존).
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
