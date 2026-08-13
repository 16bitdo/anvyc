"""사용자에게 보이는 check 설명이 실제 orchestrator 와 어긋나지 않는지 (drift guard).

`anvyc project doctor --help` 의 docstring 과 MCP tool 설명은 "이 명령이 무엇을
검사하는가" 를 사용자·에이전트에게 알리는 유일한 표면이다. check 를 추가할 때 여기를
같이 안 고치면 신규 check(예: 이 브랜치의 `gh_identity_actual`·`commit_identity_actual`)
가 **존재하는데 아무도 모르는** 상태가 된다 — 실제로 8→11 로 3개가 어긋나 있었다.

계수를 손으로 세어 하드코딩하면 같은 드리프트가 되풀이되므로, orchestrator 소스에서
실제 호출되는 check 목록을 뽑아 대조한다.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import anvyc
from anvyc.core import project_doctor


def _orchestrated_check_names() -> list[str]:
    """`run_project_doctor` 가 실제로 호출하는 check 이름 목록 (호출 순서 유지).

    이 모듈은 `_check_<name>` 함수와 `CheckResult(check_name="<name>")` 이 1:1 이다.
    """
    src = inspect.getsource(project_doctor.run_project_doctor)
    return re.findall(r"_check_(\w+)\(", src)


def test_orchestrator_check_names_are_unique_and_known() -> None:
    names = _orchestrated_check_names()
    assert len(names) == len(set(names)), f"중복 호출: {names}"
    # 이 브랜치가 추가한 두 check 가 실제로 배선돼 있는지도 함께 잠근다.
    assert "gh_identity_actual" in names
    assert "commit_identity_actual" in names


def test_cli_help_lists_every_check_with_matching_count() -> None:
    """`anvyc project doctor --help` 의 설명이 계수·목록 모두 실제와 일치해야 한다."""
    from anvyc.cli import project_doctor as cli_project_doctor

    names = _orchestrated_check_names()
    doc = inspect.getdoc(cli_project_doctor) or ""

    assert f"{len(names)} check" in doc, (
        f"CLI help 의 check 계수가 실제({len(names)})와 다름:\n{doc}"
    )
    missing = [n for n in names if n not in doc]
    assert missing == [], f"CLI help 에 누락된 check: {missing}"
    stale = re.findall(r"(\d+) check", doc)
    assert set(stale) == {str(len(names))}, f"CLI help 에 낡은 계수 잔존: {stale}"


def test_module_docstring_count_matches() -> None:
    names = _orchestrated_check_names()
    doc = project_doctor.__doc__ or ""
    assert f"{len(names)} check" in doc, f"모듈 docstring 계수 불일치:\n{doc}"
    missing = [n for n in names if n not in doc]
    assert missing == [], f"모듈 docstring 에 누락된 check: {missing}"


def _repo_root() -> Path:
    return Path(anvyc.__file__).resolve().parents[2]


def test_design_spec_lists_every_check() -> None:
    """DESIGN §33.3 이 check 명세의 SoT 문서다 — 계수와 표가 실제와 맞아야 한다."""
    names = _orchestrated_check_names()
    design = (_repo_root() / "DESIGN.md").read_text(encoding="utf-8")

    header = re.search(r"### 33\.3 project doctor check 명세 \((\d+) check\)", design)
    assert header is not None, "DESIGN.md 의 §33.3 헤더를 못 찾음 (섹션 번호/제목 변경?)"
    assert header.group(1) == str(len(names)), (
        f"DESIGN §33.3 계수({header.group(1)})가 실제({len(names)})와 다름"
    )
    missing = [n for n in names if f"`{n}`" not in design]
    assert missing == [], f"DESIGN.md 에 명세 없는 check: {missing}"


# 사용자가 읽는 문서에서 project doctor 계수를 언급하는 지점. 문구가 파일마다 달라
# 하나의 정규식으로는 못 잡으므로 지점별로 명시한다 — 새 언급을 추가하면 여기도 추가.
_DOC_COUNT_MENTIONS = (
    ("README.md", r"cwd connection 정합성 (\d+) check"),
    ("docs/multi-account.md", r"gh_account_routing 포함 (\d+) check"),
)


def test_doc_count_mentions_match() -> None:
    names = _orchestrated_check_names()
    stale: list[str] = []
    for rel, pattern in _DOC_COUNT_MENTIONS:
        text = (_repo_root() / rel).read_text(encoding="utf-8")
        found = re.findall(pattern, text)
        assert found, f"{rel} 에서 계수 언급을 못 찾음 (문구 변경? 패턴: {pattern})"
        stale += [f"{rel}: {n}" for n in found if n != str(len(names))]
    assert stale == [], f"실제({len(names)})와 다른 계수 언급: {stale}"


def test_mcp_tool_description_count_matches() -> None:
    """MCP 쪽 설명도 같이 맞춰야 한다 — 에이전트가 읽는 표면이다.

    `anvyc.mcp.server` 는 import 시점에 `SystemExit` 을 낼 수 있어(extra 미설치)
    import 하지 않고 소스 텍스트로 확인한다.
    """
    names = _orchestrated_check_names()
    src = (Path(anvyc.__file__).parent / "mcp" / "server.py").read_text(encoding="utf-8")
    counts = set(re.findall(r"정합성 (\d+) check", src))
    assert counts == {str(len(names))}, (
        f"MCP server.py 의 project_doctor check 계수가 실제({len(names)})와 다름: {counts}"
    )
