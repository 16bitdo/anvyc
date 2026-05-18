"""Metadata management.

metadata.json 생성/검증 — schemaVersion, hostname, os, arch, includedTools, files[]
"""
from __future__ import annotations

import json
import platform
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class FileEntry:
    source_path: str
    target_path: str
    sha256: str
    mode: str
    symlink_target: str | None = None
    encryption: str | None = None  # e.g. "sops/age" — apply 시 복호화 필요


@dataclass
class Metadata:
    schema_version: int = 1
    generated_at_utc: str = ""
    hostname: str = ""
    os: str = ""
    os_version: str = ""
    arch: str = ""
    anvyc_version: str = "0.1.0"
    included_tools: list[str] = field(default_factory=list)
    excluded_sensitive_paths: list[str] = field(default_factory=list)
    files: list[FileEntry] = field(default_factory=list)


def build_metadata(
    *,
    included_tools: list[str],
    excluded_sensitive_paths: list[str] | None = None,
) -> Metadata:
    """현재 환경 기준 metadata 를 생성한다 (files 는 호출측에서 채운다)."""
    return Metadata(
        generated_at_utc=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        hostname=socket.gethostname(),
        os=platform.system(),
        os_version=platform.mac_ver()[0] or platform.version(),
        arch=platform.machine(),
        included_tools=list(included_tools),
        excluded_sensitive_paths=list(excluded_sensitive_paths or []),
    )


def write_metadata(metadata: Metadata, target_dir: Path) -> Path:
    """metadata.json 을 target_dir 아래에 직렬화."""
    target = target_dir / "metadata.json"
    payload = asdict(metadata)
    # camelCase 호환 키 (DESIGN.md §18.1 예시)
    rename = {
        "schema_version": "schemaVersion",
        "generated_at_utc": "generatedAtUtc",
        "os_version": "osVersion",
        "anvyc_version": "anvycVersion",
        "included_tools": "includedTools",
        "excluded_sensitive_paths": "excludedSensitivePaths",
    }
    payload = {rename.get(k, k): v for k, v in payload.items()}
    # files[].* 도 camelCase 로
    files_out = []
    for f in payload.get("files", []):
        entry = {
            "sourcePath": f["source_path"],
            "targetPath": f["target_path"],
            "sha256": f["sha256"],
            "mode": f["mode"],
        }
        if f.get("symlink_target"):
            entry["symlinkTarget"] = f["symlink_target"]
        if f.get("encryption"):
            entry["encryption"] = f["encryption"]
        files_out.append(entry)
    payload["files"] = files_out
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return target
