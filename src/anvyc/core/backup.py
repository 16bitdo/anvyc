"""Backup workflow.

12.1 절차:
1) anvyc.yaml 로드 → 2) enabled adapter → 3) detect → 4) collect → 5) secret scan
6) 위험 시 중단 → 7) backup/<timestamp>/ 에 복사 → 8) hash → 9) metadata.json → 10) symlink
"""
from __future__ import annotations

from pathlib import Path


def run_backup(root: Path) -> Path:
    """전체 백업 워크플로를 실행하고 생성된 backup 디렉터리 경로를 반환한다 (MVP TODO)."""
    raise NotImplementedError
