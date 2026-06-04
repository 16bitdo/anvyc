"""프로젝트 컨테이너 root(`project_roots`) 변경 순수 로직.

읽기 SoT(`project_roots.py`)와 분리. anvyc.yaml 의 `project_roots` 키만 다룬다:
materialize(defaults 구체화) → add/remove/clear. 쓰기는 yaml_io.atomic_write_yaml
+ `.bak` + schema 재검증. `~` 미확장 저장(머신 간 휴대성).
"""
from __future__ import annotations

import os
from pathlib import Path


def normalize_root(raw: str) -> str:
    """strip → 후행 슬래시 제거 → `$HOME` 하위 절대경로는 `~/..` 로 재축약."""
    s = raw.strip()
    if not s:
        return ""
    if len(s) > 1:
        s = s.rstrip("/")
    home = str(Path.home())
    expanded = str(Path(s).expanduser())
    if expanded == home:
        return "~"
    if expanded.startswith(home + os.sep):
        return "~/" + expanded[len(home) + 1:]
    return s
