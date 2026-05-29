"""README §4 '지원 도구' 표 ↔ AdapterMeta SoT 동기 가드 (PR6).

scripts/gen_supported_tools.py 가 생성하는 표가 README 에 반영돼 있는지 강제한다.
새 adapter 추가/메타 변경 후 재생성을 빠뜨리면 이 테스트가 CI 에서 잡는다.
"""
from __future__ import annotations

from pathlib import Path

from anvyc.core.tools_select import render_supported_tools_markdown

_REPO = Path(__file__).resolve().parents[2]
_BEGIN = "<!-- BEGIN supported-tools"
_END = "<!-- END supported-tools -->"


def test_render_has_header_and_all_tools() -> None:
    md = render_supported_tools_markdown()
    assert md.splitlines()[0].startswith("| 도구 | 분류 |")
    for label in ("Shell (zsh)", "Git", "AWS CLI", "Cursor IDE", "Claude Code", "dev_env"):
        assert f"| {label} |" in md, f"missing tool row: {label}"


def test_readme_section4_in_sync() -> None:
    text = (_REPO / "README.md").read_text(encoding="utf-8")
    assert _BEGIN in text and _END in text, "README §4 supported-tools 마커 부재"
    _, _, rest = text.partition(_BEGIN)
    between, _, _ = rest.partition(_END)
    table_in_readme = between.split("-->", 1)[1].strip()
    assert table_in_readme == render_supported_tools_markdown(), (
        "README §4 표가 AdapterMeta SoT 와 불일치 — "
        "`python scripts/gen_supported_tools.py` 재실행 필요"
    )
