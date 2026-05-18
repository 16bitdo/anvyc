"""Diff engine.

source(backup) ↔ target(local) unified diff를 생성한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiffResult:
    target: Path
    source: Path
    unified: str
    has_change: bool


def compute_diff(source: Path, target: Path) -> DiffResult:
    """unified diff를 계산한다 (MVP TODO)."""
    raise NotImplementedError
