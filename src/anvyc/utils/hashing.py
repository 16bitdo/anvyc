"""파일 해시 계산 — backup metadata에 사용."""
from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 65536


def sha256_file(path: Path) -> str:
    """파일의 sha256 hex digest 반환."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()
