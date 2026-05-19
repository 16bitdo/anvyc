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
from anvyc.adapters.dev_env import DevEnvAdapter
from anvyc.adapters.gh import GhAdapter
from anvyc.adapters.git import GitAdapter
from anvyc.adapters.iterm2 import Iterm2Adapter
from anvyc.adapters.pulumi import PulumiAdapter
from anvyc.adapters.shell import ShellAdapter
from anvyc.core.config import AnvycConfig, load_anvyc_config
from anvyc.core.inventory import Inventory, ManagedFile, build_source_inventory
from anvyc.core.metadata import FileEntry, build_metadata, write_metadata
from anvyc.core.sops import SopsError, encrypt as sops_encrypt
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
    "dev_env": DevEnvAdapter,
}

# 단순 파일 기반 adapter — 생성자가 files tuple 만 받는다.
# anvyc.yaml 에서 tools.<name>.files 또는 tools.<name>.include 키로 override 가능.
_FILE_BASED_ADAPTERS = frozenset({"shell", "git", "aws", "gh", "pulumi"})


class BackupBlocked(RuntimeError):
    """secret scan 결과 backup 중단."""

    def __init__(
        self,
        reasons: list[str],
        *,
        next_steps: list[str] | None = None,
        allow_force: bool = True,
    ):
        super().__init__("secret scan blocked backup")
        self.reasons = reasons
        self.next_steps = next_steps or [
            "anvyc doctor",
            "anvyc scan-secrets <path>  # inspect a specific path",
        ]
        self.allow_force = allow_force


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
        if name in _FILE_BASED_ADAPTERS and tool_cfg is not None:
            user_files = tool_cfg.files or tool_cfg.include
            if user_files:
                selected.append(cls(tuple(user_files)))  # type: ignore[call-arg]
                continue
        if name == "claude" and tool_cfg is not None:
            inc = list(tool_cfg.files or []) + list(tool_cfg.include or [])
            exc = list(tool_cfg.exclude or [])
            selected.append(cls(includes=inc or None, excludes=exc or None))  # type: ignore[call-arg]
            continue
        if name == "cursor" and tool_cfg is not None:
            extra = tool_cfg.extra
            selected.append(
                cls(  # type: ignore[call-arg]
                    global_cfg=extra.get("global") or {},
                    ide_cfg=extra.get("ide") or {},
                    projects_cfg=extra.get("projects") or {},
                )
            )
            continue
        if name == "dev_env" and tool_cfg is not None:
            extra = tool_cfg.extra
            roots = tuple(extra.get("project_roots") or ())
            patterns = tuple(extra.get("patterns") or ())
            excludes = tuple(tool_cfg.exclude or ())
            selected.append(
                cls(  # type: ignore[call-arg]
                    project_roots=roots or None,
                    patterns=patterns or None,
                    excludes=excludes or None,
                )
            )
            continue
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
        if mf.symlink_target is not None:
            # symlink entry — 콘텐츠 복사 X, metadata 에만 기록
            md.files.append(
                FileEntry(
                    source_path=f"{mf.tool}/{mf.relpath}",
                    target_path=str(mf.target_path),
                    sha256="",
                    mode=f"{mf.mode:04o}",
                    symlink_target=mf.symlink_target,
                )
            )
            continue
        dest = backup_dir / mf.tool / mf.relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(mf.source_path, dest)
        mf.sha256 = sha256_file(dest)
        md.files.append(
            FileEntry(
                source_path=f"{mf.tool}/{mf.relpath}",
                target_path=str(mf.target_path),
                sha256=mf.sha256,
                mode=f"{mf.mode:04o}",
            )
        )

    # SOPS secret_files 처리 — DESIGN.md §31 + v0.4.1 per-tool + v0.5.2 per-file override
    if cfg.security.sops.enabled and cfg.security.sops.age_recipients:
        global_mode = cfg.security.sops.format  # "binary" 또는 "inplace"
        only_set = set(only) if only else None
        for tool_name, tool_cfg in cfg.tools.items():
            if only_set is not None and tool_name not in only_set:
                continue
            if not tool_cfg.enabled or not tool_cfg.secret_files:
                continue
            for spec in tool_cfg.secret_files:
                src = Path(spec.path).expanduser()
                if not src.is_file():
                    continue
                # format chain: file > tool > global > default
                sops_mode = spec.format or tool_cfg.sops_format or global_mode
                if sops_mode not in ("binary", "inplace"):
                    sops_mode = "binary"  # invalid 값은 binary 폴백
                encryption_tag = "sops/age/inplace" if sops_mode == "inplace" else "sops/age"
                canonical_str = spec.path
                # inplace 모드는 원본 확장자 유지, binary 는 .sops.json suffix
                if sops_mode == "inplace":
                    relpath = f"sops/{src.name}"
                else:
                    relpath = f"sops/{src.name}.sops.json"
                dst = backup_dir / tool_name / relpath
                try:
                    sops_encrypt(src, dst, cfg.security.sops.age_recipients, mode=sops_mode)
                except SopsError as e:
                    md.files.append(
                        FileEntry(
                            source_path=f"{tool_name}/{relpath}",
                            target_path=canonical_str,
                            sha256="",
                            mode="0600",
                            encryption=f"{encryption_tag} (FAILED: {e})",
                        )
                    )
                    continue
                # 평문 sha256 도 함께 — status/apply 의 state_before 정합화용
                plain_hash = sha256_file(src)
                md.files.append(
                    FileEntry(
                        source_path=f"{tool_name}/{relpath}",
                        target_path=canonical_str,
                        sha256=sha256_file(dst),
                        mode=f"{src.stat().st_mode & 0o777:04o}",
                        encryption=encryption_tag,
                        plain_sha256=plain_hash,
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
