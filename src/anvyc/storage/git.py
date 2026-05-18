"""Git wrapper for `.anvyc/` repo.

pre-commit hook 설치, status/commit/push wrapping. push 전 secret scan 재실행.
"""
from __future__ import annotations

from pathlib import Path


def init_repo(root: Path) -> None:
    """`.anvyc/` 영역을 Git 저장소로 초기화 (MVP TODO)."""
    raise NotImplementedError


def install_pre_commit_hook(root: Path) -> None:
    """secret scan을 실행하는 pre-commit hook을 설치한다 (MVP TODO)."""
    raise NotImplementedError


def commit(root: Path, message: str) -> None:
    """변경사항 커밋 (MVP TODO)."""
    raise NotImplementedError


def push(root: Path) -> None:
    """remote에 push. 사전 secret scan 통과 시에만 진행 (MVP TODO)."""
    raise NotImplementedError
