"""Restore workflow — apply 의 explicit backup_id 변형.

DESIGN.md §12.3. apply 와 절차 동일:
  metadata 검증 → diff → local-backup → 복사 → hash 검증

apply 와의 차이: backup_id 가 명시적으로 필수 (apply 는 current/latest 가 기본).
"""
from __future__ import annotations

from pathlib import Path

from anvyc.core.apply import ApplyReport, run_apply


def run_restore(
    root: Path | None,
    backup_id: str,
    *,
    config_path: Path | None = None,
    only: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> ApplyReport:
    """특정 backup id 의 상태로 target 을 복원한다.

    apply 와 동일한 파이프라인 (metadata → diff → local-backup → 복사 → 검증).
    apply 와의 차이는 backup_id 가 명시적 필수라는 점뿐이다.
    """
    if not backup_id:
        raise ValueError("backup_id is required for restore")
    return run_apply(
        root=root,
        backup_id=backup_id,
        config_path=config_path,
        only=only,
        dry_run=dry_run,
        force=force,
    )
