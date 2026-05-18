"""Local filesystem helpers.

`.anvyc/backups/<timestamp>/`, `.anvyc/local-backups/<timestamp>/`, `current` symlink 관리.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def new_backup_dir(root: Path) -> Path:
    """`.anvyc/backups/<timestamp>/` 경로를 생성하고 반환한다."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = root / "backups" / ts
    target.mkdir(parents=True, exist_ok=False)
    return target


def new_local_backup_dir(root: Path) -> Path:
    """apply/restore 전 자동 backup 디렉터리."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = root / "local-backups" / ts
    target.mkdir(parents=True, exist_ok=False)
    return target


def update_current_symlink(root: Path, backup_dir: Path) -> None:
    """`.anvyc/current` symlink를 새 backup으로 갱신."""
    current = root / "current"
    if current.is_symlink() or current.exists():
        current.unlink()
    current.symlink_to(backup_dir.relative_to(root))
