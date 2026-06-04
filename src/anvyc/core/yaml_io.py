"""원자적 YAML 쓰기 — tempfile.mkstemp + os.replace.

여러 config 변경 명령(tools_select / project_roots_edit)이 공유한다.
부분 쓰기로 인한 손상 방지: 같은 디렉터리에 임시 파일을 쓴 뒤 os.replace 로 교체.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def atomic_write_yaml(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
