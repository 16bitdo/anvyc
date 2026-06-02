# src/anvyc/core/guard_targets.py
"""guard 대상 repo 해소 — --project / --root / 등록 roots 에서 .git repo 수집."""
from __future__ import annotations

from pathlib import Path

from anvyc.core.project_roots import resolve_project_roots


def _git_repos_under(base: Path, max_depth: int = 2) -> list[Path]:
    if not base.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and (entry / ".git").is_dir():
            out.append(entry)
    return out


def resolve_guard_targets(
    project: list[Path] | None, root: Path | None
) -> list[Path]:
    if project:
        return [p.expanduser().resolve() for p in project if (p / ".git").is_dir()]
    bases = [root.expanduser()] if root else [Path(r).expanduser() for r in resolve_project_roots()]
    seen: set[Path] = set()
    out: list[Path] = []
    for base in bases:
        for repo in _git_repos_under(base):
            r = repo.resolve()
            if r not in seen:
                seen.add(r)
                out.append(r)
    return out
