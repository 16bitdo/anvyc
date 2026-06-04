"""INI 텍스트 안전 쓰기 + 섹션 라인 범위 탐지 (yaml_io 의 INI 형제).

`~/.aws/config` 같은 사용자 소유 INI 를 surgical 하게 편집하기 위한 저수준 도구.
configparser 는 파싱/검증에만 쓰고, 실제 쓰기는 원문 텍스트(주석 포함)를 보존하며
섹션 라인 범위만 치환한다.
"""
from __future__ import annotations

import contextlib
import os
import re
import tempfile
from pathlib import Path

_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")


def atomic_write_text(text: str, path: Path) -> None:
    """tempfile.mkstemp + os.replace 로 원자적 텍스트 쓰기 (부분쓰기 방지)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def locate_section(lines: list[str], name: str) -> tuple[int, int] | None:
    """`[name]` 섹션의 라인 범위 (start, end). 없으면 None.

    start = 헤더 라인 인덱스, end = 다음 섹션 헤더 직전(없으면 len(lines)).
    lines[start:end] = 헤더 + 본문(주석 포함). name 은 대괄호 내부 문자열 그대로.
    """
    start: int | None = None
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m is None:
            continue
        if start is None:
            if m.group("name").strip() == name:
                start = i
            continue
        return (start, i)
    if start is None:
        return None
    return (start, len(lines))
