# tests/unit/test_personal_config_guard_wiring.py
"""personal-config-guard 배선 회귀 — 가드가 **조용히 안 도는** 상태를 막는다.

2026-08-18: 이 repo 의 `core.hooksPath=scripts/hooks` 오설정을 해제해 pre-push 게이트와
pre-commit framework(gitleaks/ruff/mypy)를 되살렸다. 그 대가로, 그때까지 유일하게 돌던
personal-config-guard(`scripts/hooks/pre-commit`)가 실행되지 않게 됐다 — 훅 배치가 바뀌자
가드가 아무 신호 없이 사라진 것이다. 같은 부류의 사고가 이 세션에만 세 번 있었다
(anvyc-pr-guard 미설치 / pre-push 미실행 / 이 건).

그래서 "가드 스크립트가 잘 동작하는가"(rbr SoT 의 책임)가 아니라 **"가드가 실제로
불리도록 배선돼 있는가"** 를 시험한다. 로컬(pre-commit framework)과 server-side
(workflow) 양쪽을 고정한다 — 로컬은 `--no-verify` 로, server-side 는 훅 미설치
collaborator 환경으로 각각 뚫리기 때문이다.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRECOMMIT_CONFIG = _REPO_ROOT / ".pre-commit-config.yaml"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "personal-config-guard.yml"
_HOOK_REL = "scripts/hooks/pre-commit"
_HOOK_ID = "personal-config-guard"


def _load(path: Path) -> dict[Any, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _triggers(path: Path) -> dict[str, Any]:
    """워크플로의 트리거 매핑을 돌려준다.

    YAML 1.1 은 bare `on` 을 **불린 True 로 파싱**한다(yes/no/on/off 계열의 그 함정).
    그래서 키가 문자열 "on" 이 아니라 True 인 경우를 함께 본다 — 놓치면 트리거 검사가
    빈 dict 를 보고 **조용히 통과**한다.
    """
    cfg = _load(path)
    on = cfg.get(True, cfg.get("on"))
    return on if isinstance(on, dict) else {}


def _local_hooks(cfg: dict[Any, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for repo in cfg.get("repos") or []:
        if repo.get("repo") == "local":
            out.extend(repo.get("hooks") or [])
    return out


def test_precommit_config_declares_guard_hook() -> None:
    """로컬 커밋 게이트에 가드가 배선돼 있다."""
    hooks = _local_hooks(_load(_PRECOMMIT_CONFIG))
    ids = [h.get("id") for h in hooks]
    assert _HOOK_ID in ids, f"`.pre-commit-config.yaml` 에 {_HOOK_ID} 훅 없음 (현재: {ids})"


def test_precommit_guard_entry_points_at_tracked_hook() -> None:
    """entry 가 tracked SoT 스크립트를 가리키고 실제로 실행 가능하다.

    로직을 config 에 복제하지 않고 스크립트에 위임한다는 계약 — 경로가 어긋나면
    pre-commit 이 훅을 못 찾아 커밋 시점에야 깨진다.
    """
    hooks = _local_hooks(_load(_PRECOMMIT_CONFIG))
    hook = next((h for h in hooks if h.get("id") == _HOOK_ID), None)
    assert hook is not None, f"{_HOOK_ID} 훅 없음"

    entry = str(hook.get("entry", ""))
    assert _HOOK_REL in entry, f"entry 가 {_HOOK_REL} 를 가리키지 않음: {entry!r}"

    script = _REPO_ROOT / _HOOK_REL
    assert script.is_file(), f"가드 스크립트 부재: {script}"
    assert os.access(script, os.X_OK), f"가드 스크립트 실행권한 없음: {script}"


def test_server_side_workflow_invokes_hook_not_a_reimplementation() -> None:
    """server-side 재검사가 정규식을 재구현하지 않고 훅 자체를 부른다 (단일 SoT).

    재구현하면 두 정의가 갈려 로컬은 막고 CI 는 통과하는(또는 반대) 상태가 된다.
    """
    assert _WORKFLOW.is_file(), f"server-side 워크플로 부재: {_WORKFLOW}"
    text = _WORKFLOW.read_text(encoding="utf-8")

    assert _HOOK_REL in text, f"워크플로가 {_HOOK_REL} 를 호출하지 않음"
    assert "BLOCKED_REGEX" not in text, "워크플로가 차단 정규식을 재구현함 — 훅에 위임할 것"


def test_server_side_workflow_runs_automatically() -> None:
    """push/PR 에서 자동 실행된다 — 이 repo 는 public 이라 Actions 가 무료다.

    private repo(ccinspector)는 billing 때문에 workflow_dispatch 전용을 택했지만,
    그 제약이 없는 곳까지 on-demand 로 두면 아무도 돌리지 않아 장식이 된다.
    """
    on = _triggers(_WORKFLOW)
    assert on, "트리거 파싱 실패 — 빈 매핑"
    assert "pull_request" in on, f"pull_request 트리거 없음 (현재: {sorted(map(str, on))})"
    assert "push" in on, f"push 트리거 없음 (현재: {sorted(map(str, on))})"


def test_server_side_workflow_has_no_paths_ignore() -> None:
    """paths-ignore 를 두지 않는다 — 차단 패턴에 `CLAUDE.md`·`CONTEXT.md` 가 있다.

    `ci.yml` 은 비용 절감으로 `**.md` 를 무시하는데, 가드를 거기 얹으면 **정확히 그
    .md 차단 대상만 커밋했을 때** 검사가 통째로 건너뛰어진다. 그래서 별도 워크플로다.
    """
    on = _triggers(_WORKFLOW)
    assert on, "트리거 파싱 실패 — 빈 매핑"
    for event, spec in on.items():
        if isinstance(spec, dict):
            assert "paths-ignore" not in spec, (
                f"{event} 에 paths-ignore 존재 — .md 차단 대상(CLAUDE.md/CONTEXT.md)이 "
                "검사에서 빠진다"
            )
