"""README 동반 도구 표 ↔ EXTRAS_REGISTRY SoT 동기 가드 (step 3).

scripts/gen_extras.py 가 생성하는 표가 README 에 반영돼 있는지 강제한다.
EXTRAS_REGISTRY 변경 후 재생성을 빠뜨리면 이 테스트가 CI 에서 잡는다.
"""

from __future__ import annotations

from pathlib import Path

from anvyc.core.extras import render_extras_markdown

_REPO = Path(__file__).resolve().parents[2]
_BEGIN = "<!-- BEGIN companion-tools"
_END = "<!-- END companion-tools -->"


def test_render_has_header_and_rows() -> None:
    md = render_extras_markdown()
    assert md.splitlines()[0].startswith("| 도구 | 종류 |")
    for label in ("SOPS", "age", "1Password CLI", "mcp (MCP SDK)", "boto3 (AWS)"):
        assert f"| {label} |" in md, f"missing extra row: {label}"
    # 종류 열은 CLI / pip extra 만.
    assert "| CLI |" in md and "| pip extra |" in md


def test_readme_companion_tools_in_sync() -> None:
    text = (_REPO / "README.md").read_text(encoding="utf-8")
    assert _BEGIN in text and _END in text, "README companion-tools 마커 부재"
    _, _, rest = text.partition(_BEGIN)
    between, _, _ = rest.partition(_END)
    table_in_readme = between.split("-->", 1)[1].strip()
    assert table_in_readme == render_extras_markdown(), (
        "README 동반 도구 표가 EXTRAS_REGISTRY SoT 와 불일치 — "
        "`python scripts/gen_extras.py` 재실행 필요"
    )
