"""anvyc list — `.anvyc/backups/` 의 metadata.json 을 조회한다."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BackupSummary:
    backup_id: str            # 디렉터리명 (timestamp)
    path: Path                # backup 절대 경로
    is_current: bool
    hostname: str = ""
    os: str = ""
    arch: str = ""
    included_tools: tuple[str, ...] = ()
    file_count: int = 0
    generated_at_utc: str = ""


def list_backups(root: Path) -> list[BackupSummary]:
    """`.anvyc/backups/` 의 backup 디렉터리들을 timestamp 내림차순으로 반환."""
    backups_dir = root / "backups"
    if not backups_dir.is_dir():
        return []

    current_target: Path | None = None
    current_link = root / "current"
    if current_link.is_symlink():
        try:
            current_target = (current_link.parent / current_link.readlink()).resolve(strict=False)
        except OSError:
            current_target = None

    out: list[BackupSummary] = []
    for entry in sorted(backups_dir.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        meta_path = entry / "metadata.json"
        summary = BackupSummary(
            backup_id=entry.name,
            path=entry,
            is_current=(current_target is not None and current_target == entry.resolve()),
        )
        if meta_path.is_file():
            try:
                data = json.loads(meta_path.read_text())
                summary.hostname = str(data.get("hostname", ""))
                summary.os = str(data.get("os", ""))
                summary.arch = str(data.get("arch", ""))
                summary.included_tools = tuple(data.get("includedTools") or [])
                summary.file_count = len(data.get("files") or [])
                summary.generated_at_utc = str(data.get("generatedAtUtc", ""))
            except (json.JSONDecodeError, OSError):
                pass
        out.append(summary)
    return out
