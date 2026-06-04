"""Project root discovery — root 아래의 project 디렉터리 수집 (P2, v0.8.1).

discovery rule (D12): `.git` 또는 `Pulumi.yaml` marker 보유 디렉터리 = project.
depth ≤ 2 (root/<project>/) 까지만 — 더 깊은 nesting 은 무시 (성능 + noise).

cursor_projects_suggest 와 비슷한 패턴이지만 목적이 다르다:
- cursor_projects_suggest: cursor.projects.roots 등록 추천 (INFO)
- project_discovery: anvyc project list 의 source — read-only iterator
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from anvyc.core.project_roots import DEFAULT_PROJECT_ROOTS
from anvyc.core.project_scope import _walk_markers

PROJECT_MARKERS: tuple[str, ...] = (".git", "Pulumi.yaml")
DEFAULT_MAX_DEPTH = 2


def discover_projects(
    roots: Iterable[str] | None = None,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[Path]:
    """root 아래에서 PROJECT_MARKERS 보유 디렉터리 수집.

    Args:
        roots: scan 시작점들 (default: DEFAULT_PROJECT_ROOTS — SoT).
        max_depth: root 기준 최대 깊이 (1 = root 의 즉시 child).

    Returns:
        resolve 된 절대 경로 list (alphabetical).
    """
    roots_iter = roots if roots is not None else DEFAULT_PROJECT_ROOTS
    found: set[Path] = set()
    for root_str in roots_iter:
        root = Path(root_str).expanduser()
        if not root.is_dir():
            continue
        _walk_markers(root, depth=1, max_depth=max_depth, markers=PROJECT_MARKERS, found=found)
    return sorted(found, key=lambda p: str(p))
