"""Restore workflow.

12.3 절차:
1) backup-id → 2) metadata 검증 → 3) target local backup → 4) restore diff → 5) restore → 6) 검증
"""
from __future__ import annotations

from pathlib import Path


def run_restore(root: Path, backup_id: str) -> None:
    """특정 backup id로 복원한다 (MVP TODO)."""
    raise NotImplementedError
