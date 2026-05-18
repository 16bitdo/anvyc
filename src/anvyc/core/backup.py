"""Backup workflow.

DESIGN.md §12.1 절차:
  1) anvyc.yaml 로드   → 2) enabled adapter   → 3) detect       → 4) collect (source path)
  5) secret scan       → 6) 위험 시 중단      → 7) backup/<ts>/ 복사
  8) hash              → 9) metadata.json     → 10) current symlink
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from anvyc.adapters.aws import AwsAdapter
from anvyc.adapters.base import Adapter
from anvyc.adapters.claude import ClaudeAdapter
from anvyc.adapters.cursor import CursorAdapter
from anvyc.adapters.gh import GhAdapter
from anvyc.adapters.git import GitAdapter
from anvyc.adapters.iterm2 import Iterm2Adapter
from anvyc.adapters.pulumi import PulumiAdapter
from anvyc.adapters.shell import ShellAdapter
from anvyc.core.config import AnvycConfig, load_anvyc_config
from anvyc.core.inventory import Inventory, ManagedFile, build_source_inventory
from anvyc.core.metadata import FileEntry, build_metadata, write_metadata
from anvyc.security.policy import evaluate
from anvyc.security.scanner import ScanFinding, scan_paths
from anvyc.storage.local import new_backup_dir, update_current_symlink
from anvyc.utils.hashing import sha256_file

ADAPTERS: dict[str, type[Adapter]] = {
    "shell": ShellAdapter,
    "git": GitAdapter,
    "aws": AwsAdapter,
    "gh": GhAdapter,
    "cursor": CursorAdapter,
    "claude": ClaudeAdapter,
    "iterm2": Iterm2Adapter,
    "pulumi": PulumiAdapter,
}


class BackupBlocked(RuntimeError):
    """secret scan 결과 backup 중단."""

    def __init__(self, reasons: list[str]):
        super().__init__("secret scan blocked backup")
        self.reasons = reasons


@dataclass
class BackupResult:
    backup_dir: Path
    inventory: Inventory
    secret_findings: list[ScanFinding] = field(default_factory=list)
    skipped_tools: list[str] = field(default_factory=list)


def _select_adapters(cfg: AnvycConfig, only: list[str] | None = None) -> list[Adapter]:
    """tools.<name>.enabled 가 true 인 adapter 만 선택. only 지정 시 교집합."""
    selected: list[Adapter] = []
    only_set = set(only) if only else None
    for name, cls in ADAPTERS.items():
        if only_set is not None and name not in only_set:
            continue
        tool_cfg = cfg.tools.get(name)
        if tool_cfg is not None and not tool_cfg.enabled:
            continue
        # 단순 파일 기반 adapter 는 anvyc.yaml 의 files 키를 존중
        if name in ("shell", "git") and tool_cfg is not None and tool_cfg.files:
            selected.append(cls(tuple(tool_cfg.files)))  # type: ignore[call-arg]
        else:
            selected.append(cls())
    return selected


def run_backup(
    root: Path | None = None,
    *,
    config_path: Path | None = None,
    only: list[str] | None = None,
    force: bool = False,
) -> BackupResult:
    """전체 백업 워크플로 실행."""
    cfg = load_anvyc_config(config_path)
    if root is None:
        root = Path(cfg.storage.root)
    root = root.expanduser().resolve() if str(root).startswith("~") else root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    adapters = _select_adapters(cfg, only=only)
    inventory = build_source_inventory(adapters)

    # Secret scan (config.security.secret_scan 가 true 일 때)
    findings: list[ScanFinding] = []
    if cfg.security.secret_scan:
        findings = scan_paths([mf.source_path for mf in inventory.files])
        decision = evaluate(findings, force=force)
        if decision.block and cfg.security.block_on_secret:
            raise BackupBlocked(decision.reasons)

    backup_dir = new_backup_dir(root)
    md = build_metadata(
        included_tools=sorted({mf.tool for mf in inventory.files}),
        excluded_sensitive_paths=_gather_excludes(adapters),
    )

    for mf in inventory.files:
        dest = backup_dir / mf.tool / mf.source_path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(mf.source_path, dest)
        mf.sha256 = sha256_file(dest)
        md.files.append(
            FileEntry(
                source_path=f"{mf.tool}/{mf.source_path.name}",
                target_path=str(mf.target_path),
                sha256=mf.sha256,
                mode=f"{mf.mode:04o}",
            )
        )

    write_metadata(md, backup_dir)
    update_current_symlink(root, backup_dir)

    return BackupResult(
        backup_dir=backup_dir,
        inventory=inventory,
        secret_findings=findings,
    )


def _gather_excludes(adapters: list[Adapter]) -> list[str]:
    out: list[str] = []
    for ad in adapters:
        try:
            out.extend(ad.exclude())
        except NotImplementedError:
            continue
    return sorted(set(out))
