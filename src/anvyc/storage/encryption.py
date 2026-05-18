"""Encryption helpers — `~/.anvyc-secrets/` 영역의 암호화/복호화.

MVP에서는 age (CLI) 기반으로 stub하고, 옵션 확장 시 `cryptography` 백엔드를 추가한다.
"""
from __future__ import annotations

from pathlib import Path


def encrypt_file(src: Path, dst: Path, recipient: str) -> None:
    """src를 age로 암호화하여 dst에 저장 (MVP TODO)."""
    raise NotImplementedError


def decrypt_file(src: Path, dst: Path, identity: Path) -> None:
    """age 암호화 파일을 dst로 복호화 (MVP TODO)."""
    raise NotImplementedError
