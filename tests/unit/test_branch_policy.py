# tests/unit/test_branch_policy.py
"""Unit tests for anvyc.core.branch_policy."""
from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from anvyc.core.branch_policy import (
    FALLBACK_POLICY,
    BranchPolicy,
    enforced_merge_strategy,
    resolve_policy,
)


def _fake_proc(stdout: str, rc: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["x"], returncode=rc, stdout=stdout, stderr="")


def test_resolve_policy_parses_manifest_json(tmp_path: Path) -> None:
    payload = {
        "registered": True,
        "policy": {
            "default_branch": "main",
            "protected_branches": ["main"],
            "push_to_main_allowed": False,
            "pr_required": True,
            "pr_reviewers_min": 0,
            "merge_strategy": "squash",
        },
    }
    with patch("anvyc.core.branch_policy.find_lookup_script", return_value=tmp_path / "s.py"), \
         patch("anvyc.core.branch_policy.subprocess.run", return_value=_fake_proc(json.dumps(payload))):
        pol = resolve_policy(tmp_path)
    assert isinstance(pol, BranchPolicy)
    assert pol.push_to_main_allowed is False
    assert pol.pr_reviewers_min == 0
    assert pol.protected_branches == ("main",)
    assert pol.source == "manifest"


def test_resolve_policy_fallback_when_no_script(tmp_path: Path) -> None:
    with patch("anvyc.core.branch_policy.find_lookup_script", return_value=None):
        pol = resolve_policy(tmp_path)
    assert pol == FALLBACK_POLICY
    assert pol.push_to_main_allowed is False  # 안전 기본값
    assert pol.source == "fallback"


def test_resolve_policy_fallback_on_bad_json(tmp_path: Path) -> None:
    with patch("anvyc.core.branch_policy.find_lookup_script", return_value=tmp_path / "s.py"), \
         patch("anvyc.core.branch_policy.subprocess.run", return_value=_fake_proc("not json")):
        pol = resolve_policy(tmp_path)
    assert pol.source == "fallback"


def test_resolve_policy_defaults_when_unregistered(tmp_path: Path) -> None:
    """registered=False (exit 3) → source='defaults', 안전값 유지."""
    payload = {
        "registered": False,
        "policy": {
            "default_branch": "main",
            "protected_branches": ["main"],
            "push_to_main_allowed": False,
            "pr_required": True,
            "pr_reviewers_min": 0,
            "merge_strategy": "squash",
        },
    }
    with patch("anvyc.core.branch_policy.find_lookup_script", return_value=tmp_path / "s.py"), \
         patch("anvyc.core.branch_policy.subprocess.run", return_value=_fake_proc(json.dumps(payload), rc=3)):
        pol = resolve_policy(tmp_path)
    assert pol.source == "defaults"
    assert pol.push_to_main_allowed is False


# ── declared — manifest 항목에 직접 적은 정책 키 ─────────────────────────────
# lookup 의 policy 는 defaults 와 항목 값을 합친 결과라 물려받은 값과 직접 적은 값을
# 구분하지 못한다. merge_strategy 는 직접 적은 값만 ruleset 으로 강제한다.


def _registered_payload(declared: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "registered": True,
        "policy": {
            "default_branch": "main",
            "protected_branches": ["main"],
            "push_to_main_allowed": False,
            "pr_required": True,
            "pr_reviewers_min": 0,
            "merge_strategy": "merge",
        },
    }
    if declared is not None:
        payload["declared"] = declared
    return payload


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        (["merge_strategy", "pr_reviewers_min"], frozenset({"merge_strategy", "pr_reviewers_min"})),
        (None, frozenset()),  # declared 가 없는 옛 rbr 출력 — 아무것도 선언으로 보지 않는다
        ("merge_strategy", frozenset()),  # 목록이 아니면 글자 단위로 쪼개지 않는다
    ],
    ids=["declared", "old-lookup", "malformed"],
)
def test_resolve_policy_reads_declared_keys(
    tmp_path: Path, declared: Any, expected: frozenset[str]
) -> None:
    out = json.dumps(_registered_payload(declared))
    with patch("anvyc.core.branch_policy.find_lookup_script", return_value=tmp_path / "s.py"), \
         patch("anvyc.core.branch_policy.subprocess.run", return_value=_fake_proc(out)):
        pol = resolve_policy(tmp_path)
    assert pol.declared == expected


@pytest.mark.parametrize(
    ("source", "declared", "expected"),
    [
        ("manifest", frozenset({"merge_strategy"}), "merge"),
        ("manifest", frozenset({"pr_reviewers_min"}), None),  # 항목에 안 적음 — defaults 상속
        ("defaults", frozenset({"merge_strategy"}), None),  # manifest 밖
        ("fallback", frozenset({"merge_strategy"}), None),
    ],
    ids=["declared", "inherited", "unregistered", "fallback"],
)
def test_enforced_merge_strategy_only_for_declared_manifest_value(
    source: str, declared: frozenset[str], expected: str | None
) -> None:
    pol = dataclasses.replace(
        FALLBACK_POLICY, merge_strategy="merge", source=source, declared=declared
    )
    assert enforced_merge_strategy(pol) == expected
