"""Path helpers — `~` 확장, symlink 해석, 상대/절대 변환."""
from __future__ import annotations

from pathlib import Path


def expand(p: str | Path) -> Path:
    """`~` 와 환경변수를 확장한 절대 경로 반환."""
    return Path(p).expanduser().resolve()


def safe_relative(target: Path, base: Path) -> Path:
    """target이 base 하위가 아닐 때 ValueError 대신 명시적으로 처리할 helper."""
    try:
        return target.relative_to(base)
    except ValueError:
        return target
