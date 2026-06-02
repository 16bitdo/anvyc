# tests/unit/test_branch_policy.py
"""Unit tests for anvyc.core.branch_policy."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from anvyc.core.branch_policy import (
    FALLBACK_POLICY,
    BranchPolicy,
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
