"""Cost cache (CP-13 PR-13B1).

Layout: `~/.config/anvyc/cost/cache/<source>/<account>/<YYYY-MM-DD>.json`.
Atomic write (tempfile + `os.replace`) — CP-4 snapshot / CP-6 sync 의
atomic 패턴 미러. read 는 graceful (부재 / parse 실패 시 `None`).

retention 정책 (raw 90d / aggregate 24m) 의 `gc` 명령은 PR-13B2 에서.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from anvyc.core.cost.ledger import CostReport

CACHE_ROOT = Path.home() / ".config" / "anvyc" / "cost" / "cache"


def cache_path(
    source: str,
    account: str,
    day: date,
    root: Path | None = None,
) -> Path:
    """`<root>/<source>/<account>/<YYYY-MM-DD>.json` 경로 계산."""
    base = root or CACHE_ROOT
    return base / source / account / f"{day.isoformat()}.json"


def write_cache(
    report: CostReport,
    day: date,
    root: Path | None = None,
) -> Path:
    """atomic write. parent 디렉토리 자동 생성. 실패 시 tempfile cleanup."""
    path = cache_path(report.source, report.account, day, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".cost-", suffix=".json.tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                report.to_dict(), f, ensure_ascii=False, indent=2
            )
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def read_cache(path: Path) -> CostReport | None:
    """경로 부재 / JSON parse 실패 / schema 불일치 시 `None` (graceful)."""
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return CostReport.from_dict(data)
    except (KeyError, ValueError, TypeError):
        return None


def iter_cache_files(
    source: str | None = None,
    account: str | None = None,
    root: Path | None = None,
) -> Iterator[Path]:
    """모든 cache .json 을 sorted yield. source / account filter 옵션."""
    base = root or CACHE_ROOT
    if not base.is_dir():
        return
    sources = (
        [source]
        if source
        else sorted(p.name for p in base.iterdir() if p.is_dir())
    )
    for src in sources:
        src_dir = base / src
        if not src_dir.is_dir():
            continue
        accts = (
            [account]
            if account
            else sorted(p.name for p in src_dir.iterdir() if p.is_dir())
        )
        for acct in accts:
            acct_dir = src_dir / acct
            if not acct_dir.is_dir():
                continue
            yield from sorted(acct_dir.glob("*.json"))


__all__ = [
    "CACHE_ROOT",
    "cache_path",
    "iter_cache_files",
    "read_cache",
    "write_cache",
]
