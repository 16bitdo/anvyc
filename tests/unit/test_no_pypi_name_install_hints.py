"""src 에 PyPI 이름 기반 설치 안내가 없다.

anvyc 는 PyPI 에 없다(2026-10-07: simple·JSON·TestPyPI 모두 404). 이름으로 찾는 설치 안내는 새
환경에서 실패하고, 누군가 그 이름을 올리면 그 패키지를 설치한다. 주석·docstring 도 본다 —
설명이 필요하면 명령 꼴이 아닌 말로 쓴다.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "anvyc"
# 설치 명령 뒤 60자 안에 경로가 아닌 `anvyc[…]` 가 오고 ` @ ` 로 이어지지 않는 꼴.
_NAME_BASED = re.compile(
    r"(?:pip install|uv tool install|pipx install)\b.{0,60}?(?<![\w/.-])anvyc\[[^\]]*\](?!\s*@)"
)


def test_no_name_based_install_hint_in_src() -> None:
    hits: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        # 줄을 이어 붙여 본다 — 명령과 extras 가 다음 줄로 넘어간 docstring 도 잡는다.
        text = re.sub(r"\s*\n\s*", " ", path.read_text(encoding="utf-8"))
        hits.extend(f"{path.relative_to(_SRC.parent)}: {m.group(0)}" for m in _NAME_BASED.finditer(text))
    assert hits == [], "PyPI 이름 기반 설치 안내:\n" + "\n".join(hits)
