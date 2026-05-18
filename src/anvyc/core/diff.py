"""Diff engine.

source(backup) ↔ target(local) 의 unified diff 를 생성한다.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiffResult:
    target: Path        # canonical (~/) 또는 expanded
    source: Path        # backup 측 경로
    unified: str
    has_change: bool


def _read_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError:
        return []


def compute_diff(source: Path, target: Path, *, label_source: str | None = None,
                 label_target: str | None = None) -> DiffResult:
    """source(=backup) → target(=current local) 방향 unified diff."""
    src_lines = _read_lines(source)
    tgt_lines = _read_lines(target)
    a_label = label_source or f"backup:{source.name}"
    b_label = label_target or f"target:{target}"
    diff_iter = difflib.unified_diff(
        src_lines, tgt_lines, fromfile=a_label, tofile=b_label, lineterm=""
    )
    unified = "\n".join(diff_iter)
    return DiffResult(
        target=target,
        source=source,
        unified=unified,
        has_change=bool(unified),
    )
