# src/anvyc/core/guard_targets.py
"""guard 대상 repo 해소 — --project / --root / 등록 roots 에서 .git repo 수집."""
from __future__ import annotations

from pathlib import Path


def resolve_guard_targets(
    project: list[Path] | None, root: Path | None
) -> list[Path]:
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
