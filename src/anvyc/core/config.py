"""anvyc.yaml 최소 로더.

전체 schema 검증은 후속 task (pydantic 모델). 현재 PoC 는 doctor.cross_user 영역만 필요.
파일이 없거나 키가 없는 경우 안전한 기본값을 반환한다.
"""
from __future__ import annotations

import getpass
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from anvyc.checks.base import CheckContext

DEFAULT_SCAN_TARGETS: tuple[str, ...] = (
    "~/.cursor/projects",
    "~/.zshrc",
    "~/.zprofile",
    "~/.gitconfig",
    "~/.ssh/config",
    "~/.ssh/config.d",
    "~/Library/Application Support/Cursor/User/settings.json",
    "~/Library/Application Support/Cursor/User/keybindings.json",
    "~/.claude/settings.json",
    "~/.claude/CLAUDE.md",
)


@dataclass
class DoctorConfig:
    enabled: bool = True
    known_user_aliases: dict[str, str] = field(default_factory=dict)
    scan_targets: list[str] = field(default_factory=lambda: list(DEFAULT_SCAN_TARGETS))
    severity_overrides: dict[str, str] = field(default_factory=dict)


def load_config(path: Path | None = None) -> DoctorConfig:
    """anvyc.yaml 에서 doctor.cross_user 섹션만 읽어 DoctorConfig 를 반환한다."""
    candidates: list[Path] = []
    if path is not None:
        candidates.append(path)
    candidates.extend(
        [
            Path.cwd() / "anvyc.yaml",
            Path.cwd() / ".anvyc" / "anvyc.yaml",
            Path("~/.anvyc/anvyc.yaml").expanduser(),
        ]
    )

    raw: dict = {}
    for c in candidates:
        if c.exists() and c.is_file():
            try:
                with c.open("r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                break
            except (OSError, yaml.YAMLError):
                continue

    cu = (raw.get("doctor") or {}).get("cross_user") or {}
    return DoctorConfig(
        enabled=bool(cu.get("enabled", True)),
        known_user_aliases=dict(cu.get("known_user_aliases") or {}),
        scan_targets=list(cu.get("scan_targets") or DEFAULT_SCAN_TARGETS),
        severity_overrides=dict(cu.get("severity_overrides") or {}),
    )


def build_check_context(cfg: DoctorConfig) -> CheckContext:
    """DoctorConfig → CheckContext 변환 (~ 확장 포함)."""
    return CheckContext(
        current_user=getpass.getuser(),
        known_user_aliases=cfg.known_user_aliases,
        scan_targets=[Path(p).expanduser() for p in cfg.scan_targets],
    )
