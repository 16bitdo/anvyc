# src/anvyc/core/branch_policy.py
"""branch-strategies.yaml(role-based-ruleset) 정책을 해소한다.

SoT 는 role-based-ruleset. anvyc 는 그 `scripts/lookup_branch_strategy.py` 를
subprocess 로 호출(--format json)해 정책을 읽고, 스크립트/매니페스트가 없으면
안전 fallback(push_to_main_allowed=false)을 쓴다. DESIGN.md 신규 CP 참고.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

RULESET_DIR_ENV = "ANVYC_RULESET_DIR"
DEFAULT_RULESET_DIR = Path("~/dev/role-based-ruleset")


@dataclass(frozen=True)
class BranchPolicy:
    default_branch: str
    protected_branches: tuple[str, ...]
    push_to_main_allowed: bool
    pr_required: bool
    pr_reviewers_min: int
    merge_strategy: str
    source: str  # "manifest" | "defaults" | "fallback"


FALLBACK_POLICY = BranchPolicy(
    default_branch="main",
    protected_branches=("main",),
    push_to_main_allowed=False,
    pr_required=True,
    pr_reviewers_min=0,
    merge_strategy="squash",
    source="fallback",
)


def find_lookup_script() -> Path | None:
    base = os.environ.get(RULESET_DIR_ENV)
    root = Path(base).expanduser() if base else DEFAULT_RULESET_DIR.expanduser()
    script = root / "scripts" / "lookup_branch_strategy.py"
    return script if script.is_file() else None


def resolve_policy(repo_dir: Path) -> BranchPolicy:
    """repo_dir 의 branch 정책을 ruleset lookup 으로 해소. 실패 시 FALLBACK_POLICY."""
    script = find_lookup_script()
    if script is None:
        return FALLBACK_POLICY
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--cwd", str(repo_dir), "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # TimeoutExpired ⊂ SubprocessError
        return FALLBACK_POLICY
    # exit 0=matched, 3=defaults(둘 다 json 출력); 그 외/빈출력 → fallback
    if proc.returncode not in (0, 3) or not proc.stdout.strip():
        return FALLBACK_POLICY
    try:
        data = json.loads(proc.stdout)
        pol = data["policy"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return FALLBACK_POLICY
    return BranchPolicy(
        default_branch=str(pol.get("default_branch", "main")),
        protected_branches=tuple(pol.get("protected_branches") or ["main"]),
        push_to_main_allowed=bool(pol.get("push_to_main_allowed", False)),
        pr_required=bool(pol.get("pr_required", True)),
        pr_reviewers_min=int(pol.get("pr_reviewers_min", 0)),
        merge_strategy=str(pol.get("merge_strategy", "squash")),
        source="manifest" if data.get("registered") else "defaults",
    )
