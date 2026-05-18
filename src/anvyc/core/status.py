"""anvyc status — backup vs 현재 target 파일 drift 계산."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from anvyc.utils.hashing import sha256_file


@dataclass
class FileStatus:
    tool: str
    source_path: Path        # backup 안의 파일
    target_path: Path        # canonical (~/) 경로
    target_resolved: Path    # ~ 확장된 절대 경로
    expected_sha256: str
    actual_sha256: str | None
    state: str               # "unchanged" | "modified" | "missing"


@dataclass
class StatusReport:
    backup_dir: Path
    entries: list[FileStatus] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"unchanged": 0, "modified": 0, "missing": 0}
        for e in self.entries:
            out[e.state] = out.get(e.state, 0) + 1
        return out


def _pick_backup(root: Path, backup_id: str | None) -> Path:
    if backup_id:
        candidate = root / "backups" / backup_id
        if candidate.is_dir():
            return candidate
        raise FileNotFoundError(f"backup not found: {backup_id}")
    current = root / "current"
    if current.is_symlink():
        return (current.parent / current.readlink()).resolve(strict=False)
    backups = root / "backups"
    if backups.is_dir():
        dirs = sorted([d for d in backups.iterdir() if d.is_dir()], reverse=True)
        if dirs:
            return dirs[0]
    raise FileNotFoundError("no backup found under .anvyc/backups/")


def compute_status(root: Path, backup_id: str | None = None) -> StatusReport:
    """metadata.json 의 sha256/targetPath 와 현재 target 의 실제 sha256 을 비교."""
    backup_dir = _pick_backup(root, backup_id)
    meta_path = backup_dir / "metadata.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"metadata.json missing in {backup_dir}")

    data = json.loads(meta_path.read_text())
    report = StatusReport(backup_dir=backup_dir)

    for entry in data.get("files") or []:
        target_canonical = Path(str(entry.get("targetPath", "")))
        target_resolved = target_canonical.expanduser()
        expected = str(entry.get("sha256", ""))
        source_path = backup_dir / str(entry.get("sourcePath", ""))

        actual: str | None
        if not target_resolved.exists():
            state = "missing"
            actual = None
        else:
            try:
                actual = sha256_file(target_resolved)
                state = "unchanged" if actual == expected else "modified"
            except OSError:
                actual = None
                state = "missing"

        # tool 은 sourcePath 의 첫 segment 로부터 추출 (예: "shell/.zshrc" → "shell")
        tool = ""
        sp = str(entry.get("sourcePath", ""))
        if "/" in sp:
            tool = sp.split("/", 1)[0]

        report.entries.append(
            FileStatus(
                tool=tool,
                source_path=source_path,
                target_path=target_canonical,
                target_resolved=target_resolved,
                expected_sha256=expected,
                actual_sha256=actual,
                state=state,
            )
        )
    return report
