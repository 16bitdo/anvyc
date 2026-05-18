"""Metadata management.

metadata.json 생성/검증 — schemaVersion, hostname, os, arch, includedTools, files[]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FileEntry:
    source_path: str
    target_path: str
    sha256: str
    mode: str


@dataclass
class Metadata:
    schema_version: int = 1
    generated_at_utc: datetime = field(default_factory=datetime.utcnow)
    hostname: str = ""
    os: str = ""
    os_version: str = ""
    arch: str = ""
    anvyc_version: str = "0.1.0"
    included_tools: list[str] = field(default_factory=list)
    excluded_sensitive_paths: list[str] = field(default_factory=list)
    files: list[FileEntry] = field(default_factory=list)


def build_metadata() -> Metadata:
    """현재 환경 기준 metadata를 생성한다 (MVP TODO)."""
    raise NotImplementedError
