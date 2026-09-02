"""DESIGN §27.1.1 표가 실제 `_REGISTRY` 와 어긋나지 않는지 (drift guard).

전역 doctor 의 check 목록은 `core/doctor.py:_REGISTRY` 가 SoT 이고, DESIGN §27.1.1
표가 그것을 사람에게 설명하는 유일한 표면이다. check 를 추가할 때 표를 같이 안 고치면
**존재하는데 문서에 없는** check 가 쌓인다 — 2026-09-02 실측에서 5개가 그 상태였다
(`secret-registry-valid`·`tui-extra-importable`·`aws-account-status`·
`claude-md-freshness`·`ruleset-deploy-drift`).

project doctor 쪽은 `test_project_doctor_check_count` 가 같은 역할을 하는데 전역
doctor 에는 없었다. 그래서 v0.17.0 부터 v0.21.0 까지 누적된 것이다.

**계수가 아니라 이름 집합으로 대조한다.** 계수만 보면 하나 빠지고 하나 늘어난 교체를
그대로 통과시킨다 — 문서 drift 는 대개 그 형태로 온다.
"""
from __future__ import annotations

import re
from pathlib import Path

import anvyc
from anvyc.core.doctor import _REGISTRY


def _repo_root() -> Path:
    return Path(anvyc.__file__).resolve().parents[2]


def _design_section() -> str:
    """DESIGN §27.1.1 본문 (다음 섹션 헤더 직전까지)."""
    design = (_repo_root() / "DESIGN.md").read_text(encoding="utf-8")
    start = design.index("#### 27.1.1")
    end = design.index("### 27.2", start)
    return design[start:end]


def _listed_check_names(section: str) -> set[str]:
    """표 첫 열의 `check_name` 들. 헤더 행(`| check_name |`)은 백틱이 없어 안 걸린다."""
    return set(re.findall(r"^\| `([a-z0-9-]+)` \|", section, re.M))


def test_design_table_lists_every_registered_check() -> None:
    section = _design_section()
    listed = _listed_check_names(section)
    registered = set(_REGISTRY)

    missing = sorted(registered - listed)
    extra = sorted(listed - registered)
    assert not missing, f"DESIGN §27.1.1 표에 없는 등록 check: {missing}"
    assert not extra, f"DESIGN §27.1.1 표에만 있는(제거된?) check: {extra}"


def test_design_section_header_states_actual_count() -> None:
    """헤더의 계수도 함께 잠근다 — 표를 고치고 헤더를 잊는 것이 다음 drift 다."""
    section = _design_section()
    header = section.splitlines()[0]
    m = re.search(r"\((\d+) check\)", header)
    assert m is not None, f"§27.1.1 헤더에 '(N check)' 표기가 없다: {header}"
    assert m.group(1) == str(len(_REGISTRY)), (
        f"§27.1.1 헤더 계수({m.group(1)})가 실제({len(_REGISTRY)})와 다름"
    )


# 사용자·에이전트가 읽는 표면에서 전역 doctor 계수를 언급하는 지점. 문구가 파일마다
# 달라 하나의 정규식으로는 못 잡으므로 지점별로 명시한다 — 새 언급을 추가하면 여기도.
_DOC_COUNT_MENTIONS = (
    ("README.md", r"환경 진단 \((\d+) check"),
    ("docs/mcp-integration.md", r"`\{results\}` \((\d+) check\)"),
    ("DESIGN.md", r"✓ \d+/(\d+) checks clean"),
)


def test_doc_count_mentions_match() -> None:
    stale: list[str] = []
    for rel, pattern in _DOC_COUNT_MENTIONS:
        text = (_repo_root() / rel).read_text(encoding="utf-8")
        found = re.findall(pattern, text)
        assert found, f"{rel} 에서 계수 언급을 못 찾음 (문구 변경? 패턴: {pattern})"
        stale += [f"{rel}: {n}" for n in found if n != str(len(_REGISTRY))]
    assert stale == [], f"실제({len(_REGISTRY)})와 다른 계수 언급: {stale}"
