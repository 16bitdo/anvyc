"""Apply workflow.

DESIGN.md §12.2 절차:
  1) anvyc.yaml 로드     → 2) backup_id 선택       → 3) metadata.json 로드
  4) diff 계산           → 5) secret scan          → 6) local-backup 자동 생성
  7) 파일 적용 (copy + mode) → 8) hash 검증        → 9) report

Adapter.apply() 가 NotImplementedError 인 경우 orchestrator 가 기본 동작
(shutil.copy2 + chmod + sha256 검증) 으로 대체한다. iTerm2 같이 plist 머지가
필요한 adapter 만 자체 apply() 를 제공한다 (Phase 2.5 이후).
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from anvyc.core.config import load_anvyc_config
from anvyc.core.status import pick_backup
from anvyc.security.policy import evaluate
from anvyc.security.scanner import ScanFinding, scan_paths
from anvyc.storage.local import new_local_backup_dir
from anvyc.utils.hashing import sha256_file


class ApplyBlocked(RuntimeError):
    """secret scan 결과 apply 차단."""

    def __init__(
        self,
        reasons: list[str],
        *,
        next_steps: list[str] | None = None,
        allow_force: bool = True,
    ):
        super().__init__("secret scan blocked apply")
        self.reasons = reasons
        self.next_steps = next_steps or [
            "anvyc doctor",
            "anvyc diff --backup-id <id>  # review changes before applying",
        ]
        self.allow_force = allow_force


@dataclass
class FileApplyEntry:
    tool: str
    relpath: str                   # backup 내 tool root 기준 상대 경로 (예: "hooks/script.sh")
    source_path: Path              # backup 안의 파일
    target_path: Path              # canonical (~/) 경로
    target_resolved: Path          # ~ 확장된 실제 경로
    expected_sha256: str
    mode: int                      # e.g. 0o600
    state_before: str              # "unchanged" | "modified" | "missing"
    state_after: str               # "applied" | "skipped" | "would_apply" | "would_skip" | "error"
    error: str | None = None
    symlink_target: str | None = None  # None 이 아니면 symlink — os.symlink 로 재생성
    encryption: str | None = None      # e.g. "sops/age" — SOPS 복호화 필요


@dataclass
class ApplyReport:
    backup_dir: Path
    local_backup_dir: Path | None
    dry_run: bool
    entries: list[FileApplyEntry] = field(default_factory=list)
    secret_findings: list[ScanFinding] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entries:
            out[e.state_after] = out.get(e.state_after, 0) + 1
        return out

    def has_error(self) -> bool:
        return any(e.state_after == "error" for e in self.entries)


def _parse_mode(s: str) -> int:
    s = s.strip()
    try:
        return int(s, 8)
    except ValueError:
        try:
            return int(s)
        except ValueError:
            return 0o600


def _load_metadata(backup_dir: Path) -> dict:
    meta_path = backup_dir / "metadata.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"metadata.json missing in {backup_dir}")
    return json.loads(meta_path.read_text())


def _build_entries(backup_dir: Path, only_tools: set[str] | None) -> list[FileApplyEntry]:
    meta = _load_metadata(backup_dir)
    entries: list[FileApplyEntry] = []
    for raw in meta.get("files") or []:
        src_rel = str(raw.get("sourcePath", ""))
        tool, _, relpath_in_tool = src_rel.partition("/")
        if not relpath_in_tool:
            # sourcePath 가 "tool/file" 이 아니면 폴백
            relpath_in_tool = tool
            tool = ""
        if only_tools is not None and tool not in only_tools:
            continue
        src = backup_dir / src_rel
        canonical = Path(str(raw.get("targetPath", "")))
        resolved = canonical.expanduser()
        expected = str(raw.get("sha256", ""))
        mode = _parse_mode(str(raw.get("mode", "0600")))
        symlink_target = raw.get("symlinkTarget")
        encryption = raw.get("encryption")
        plain_sha256 = raw.get("plainSha256")

        state_before: str
        if symlink_target is not None:
            # symlink entry — 현재 target 이 같은 symlink 인지 비교
            if resolved.is_symlink():
                try:
                    current_target = os.readlink(resolved)
                except OSError:
                    current_target = None
                state_before = "unchanged" if current_target == symlink_target else "modified"
            else:
                state_before = "missing"
        elif not resolved.exists():
            state_before = "missing"
        else:
            try:
                if encryption and plain_sha256:
                    # encrypted entry: target 평문 vs plainSha256
                    actual = sha256_file(resolved)
                    state_before = "unchanged" if actual == plain_sha256 else "modified"
                else:
                    # adapter target_hash override (iTerm2 등) 우선
                    from anvyc.core.status import _adapter_target_hash
                    actual = _adapter_target_hash(tool, resolved)
                    state_before = "unchanged" if actual == expected else "modified"
            except OSError:
                state_before = "missing"

        entries.append(
            FileApplyEntry(
                tool=tool,
                relpath=relpath_in_tool,
                source_path=src,
                target_path=canonical,
                target_resolved=resolved,
                expected_sha256=expected,
                mode=mode,
                state_before=state_before,
                state_after="pending",
                symlink_target=symlink_target,
                encryption=encryption,
            )
        )
    return entries


def _default_apply(entry: FileApplyEntry) -> None:
    """기본 apply 동작: source → target 복사, mode 보정, sha256 검증."""
    entry.target_resolved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(entry.source_path, entry.target_resolved)
    try:
        entry.target_resolved.chmod(entry.mode)
    except OSError:
        # 일부 파일시스템은 chmod 가 의미 없거나 권한 부족 — 무시
        pass
    actual = sha256_file(entry.target_resolved)
    if actual != entry.expected_sha256:
        raise RuntimeError(
            f"sha256 mismatch after copy ({actual[:12]} != {entry.expected_sha256[:12]})"
        )


def _apply_symlink(entry: FileApplyEntry) -> None:
    """symlink 재생성. target 부재 시 WARNING (skip 은 호출측 책임 X — 여기서 안 raise)."""
    target = entry.target_resolved
    if target.is_symlink() or target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(entry.symlink_target, target)


def _apply_sops(entry: FileApplyEntry, identity_file: Path | None) -> None:
    """SOPS 암호화 파일을 복호화해 target 에 평문으로 저장. DESIGN.md §31.6.

    entry.encryption 의 끝이 "/inplace" 면 inplace 모드, 그 외엔 binary.
    """
    from anvyc.core.sops import decrypt as sops_decrypt

    mode = "inplace" if (entry.encryption or "").endswith("/inplace") else "binary"
    target = entry.target_resolved
    target.parent.mkdir(parents=True, exist_ok=True)
    sops_decrypt(entry.source_path, target, identity_file=identity_file, mode=mode)
    try:
        target.chmod(entry.mode)
    except OSError:
        pass


def _apply_entry(entry: FileApplyEntry, identity_file: Path | None = None) -> None:
    """adapter 가 custom apply() 를 제공하면 그것을 호출, 아니면 _default_apply.

    symlink entry → os.symlink 분기.
    encryption=sops/age entry → sops 복호화 분기.
    iterm2 처럼 plist deep-merge 가 필요한 경우 adapter.apply() 가 동작한다.
    """
    if entry.symlink_target is not None:
        _apply_symlink(entry)
        return
    if entry.encryption and entry.encryption.startswith("sops/"):
        _apply_sops(entry, identity_file=identity_file)
        return

    # 지연 import — apply.py ↔ backup.py 순환 회피
    from anvyc.core.backup import ADAPTERS as _ADAPTERS

    cls = _ADAPTERS.get(entry.tool)
    if cls is not None:
        adapter = cls()
        try:
            adapter.apply(entry.source_path, entry.target_resolved)
            return
        except NotImplementedError:
            pass
    _default_apply(entry)


def run_apply(
    root: Path | None = None,
    *,
    backup_id: str | None = None,
    config_path: Path | None = None,
    only: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> ApplyReport:
    """전체 apply 워크플로 실행."""
    cfg = load_anvyc_config(config_path)
    if root is None:
        root = Path(cfg.storage.root)
    root = root.expanduser().resolve() if str(root).startswith("~") else root.resolve()

    backup_dir = pick_backup(root, backup_id)
    only_set = set(only) if only else None
    entries = _build_entries(backup_dir, only_set)

    # Secret scan (defense in depth — backup 단계에서도 했지만 source 가 손상/편집됐을 수 있음)
    findings: list[ScanFinding] = []
    if cfg.security.secret_scan:
        findings = scan_paths([e.source_path for e in entries if e.source_path.is_file()])
        decision = evaluate(findings, force=force)
        if decision.block and cfg.security.block_on_secret:
            raise ApplyBlocked(decision.reasons)

    if dry_run:
        for e in entries:
            e.state_after = (
                "would_skip" if e.state_before == "unchanged" else "would_apply"
            )
        return ApplyReport(
            backup_dir=backup_dir,
            local_backup_dir=None,
            dry_run=True,
            entries=entries,
            secret_findings=findings,
        )

    # local-backup of current targets (apply 가 덮어쓸 파일들)
    local_backup_dir = new_local_backup_dir(root)
    for e in entries:
        if e.state_before == "unchanged":
            continue
        if e.symlink_target is not None:
            # symlink 은 데이터가 아니라 포인터 — local-backup 생략. 롤백은 다른 backup_id 로 restore.
            continue
        if not e.target_resolved.exists():
            continue
        dest = local_backup_dir / e.tool / e.relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(e.target_resolved, dest)
        except OSError:
            # 읽기 권한 없음 등 — skip but continue
            pass

    # SOPS identity file 결정 (apply 시점에 복호화 필요)
    sops_identity: Path | None = None
    if cfg.security.sops.enabled and cfg.security.sops.age_identity_file:
        cand = Path(cfg.security.sops.age_identity_file).expanduser()
        if cand.is_file():
            sops_identity = cand

    # Apply 본체
    for e in entries:
        if e.state_before == "unchanged":
            # SOPS entry 도 plain_sha256 정합화 (v0.4.0) 후엔 정확히 비교 가능
            e.state_after = "skipped"
            continue
        try:
            _apply_entry(e, identity_file=sops_identity)
            e.state_after = "applied"
        except (OSError, RuntimeError) as err:
            e.state_after = "error"
            e.error = str(err)

    return ApplyReport(
        backup_dir=backup_dir,
        local_backup_dir=local_backup_dir,
        dry_run=False,
        entries=entries,
        secret_findings=findings,
    )
