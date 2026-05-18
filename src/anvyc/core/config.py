"""anvyc.yaml 최소 로더.

전체 schema 검증은 후속 task (pydantic 모델). 현재는 backup/doctor 동작에 필요한 영역만.
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
    "~/.cursor/mcp.json",
    "~/.zshrc",
    "~/.zprofile",
    "~/.gitconfig",
    "~/.ssh/config",
    "~/.ssh/config.d",
    "~/Library/Application Support/Cursor/User/settings.json",
    "~/Library/Application Support/Cursor/User/keybindings.json",
    "~/.claude/settings.json",
    "~/.claude/CLAUDE.md",
    "~/Library/Preferences/com.googlecode.iterm2.plist",
)


@dataclass
class StorageConfig:
    root: str = ".anvyc"
    keep_backups: int = 5
    keep_local_backups: int = 5


@dataclass
class SopsConfig:
    enabled: bool = False
    age_recipients: list[str] = field(default_factory=list)
    age_identity_file: str = "~/.config/sops/age/keys.txt"
    format: str = "binary"   # "binary" (default, byte-for-byte) | "inplace" (yaml/json 의 값만 암호화)


@dataclass
class SecurityConfig:
    secret_scan: bool = True
    block_on_secret: bool = True
    allow_encrypted_secrets: bool = True
    sops: SopsConfig = field(default_factory=SopsConfig)


@dataclass
class ToolConfig:
    enabled: bool = True
    files: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    secret_files: list[str] = field(default_factory=list)
    sops_format: str | None = None   # None 이면 전역 security.sops.format 사용
    extra: dict = field(default_factory=dict)


@dataclass
class DoctorConfig:
    enabled: bool = True
    known_user_aliases: dict[str, str] = field(default_factory=dict)
    scan_targets: list[str] = field(default_factory=lambda: list(DEFAULT_SCAN_TARGETS))
    severity_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class AnvycConfig:
    storage: StorageConfig = field(default_factory=StorageConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    tools: dict[str, ToolConfig] = field(default_factory=dict)
    doctor: DoctorConfig = field(default_factory=DoctorConfig)
    source: Path | None = None  # 로드된 yaml 경로 (debug 용)


def _read_yaml(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _candidate_paths(path: Path | None) -> list[Path]:
    out: list[Path] = []
    if path is not None:
        out.append(path)
    out.extend(
        [
            Path.cwd() / "anvyc.yaml",
            Path.cwd() / ".anvyc" / "anvyc.yaml",
            Path("~/.anvyc/anvyc.yaml").expanduser(),
        ]
    )
    return out


def load_anvyc_config(path: Path | None = None) -> AnvycConfig:
    """anvyc.yaml 전체를 읽어 AnvycConfig 로 반환. 없으면 기본값."""
    raw: dict = {}
    source: Path | None = None
    for c in _candidate_paths(path):
        if c.exists() and c.is_file():
            raw = _read_yaml(c)
            source = c
            break

    storage_raw = raw.get("storage") or {}
    storage = StorageConfig(
        root=str(storage_raw.get("root") or ".anvyc"),
        keep_backups=int(storage_raw.get("keep_backups") or 5),
        keep_local_backups=int(storage_raw.get("keep_local_backups") or 5),
    )

    sec_raw = raw.get("security") or {}
    sops_raw = sec_raw.get("sops") or {}
    sops = SopsConfig(
        enabled=bool(sops_raw.get("enabled", False)),
        age_recipients=list(sops_raw.get("age_recipients") or []),
        age_identity_file=str(
            sops_raw.get("age_identity_file") or "~/.config/sops/age/keys.txt"
        ),
        format=str(sops_raw.get("format") or "binary"),
    )
    security = SecurityConfig(
        secret_scan=bool(sec_raw.get("secret_scan", True)),
        block_on_secret=bool(sec_raw.get("block_on_secret", True)),
        allow_encrypted_secrets=bool(sec_raw.get("allow_encrypted_secrets", True)),
        sops=sops,
    )

    tools_raw = raw.get("tools") or {}
    tools: dict[str, ToolConfig] = {}
    for name, body in tools_raw.items():
        body = body or {}
        known = {"enabled", "files", "include", "exclude", "secret_files", "sops_format"}
        extra = {k: v for k, v in body.items() if k not in known}
        sops_format_raw = body.get("sops_format")
        tools[name] = ToolConfig(
            enabled=bool(body.get("enabled", True)),
            files=list(body.get("files") or []),
            include=list(body.get("include") or []),
            exclude=list(body.get("exclude") or []),
            secret_files=list(body.get("secret_files") or []),
            sops_format=str(sops_format_raw) if sops_format_raw else None,
            extra=extra,
        )

    cu = (raw.get("doctor") or {}).get("cross_user") or {}
    doctor = DoctorConfig(
        enabled=bool(cu.get("enabled", True)),
        known_user_aliases=dict(cu.get("known_user_aliases") or {}),
        scan_targets=list(cu.get("scan_targets") or DEFAULT_SCAN_TARGETS),
        severity_overrides=dict(cu.get("severity_overrides") or {}),
    )

    return AnvycConfig(
        storage=storage,
        security=security,
        tools=tools,
        doctor=doctor,
        source=source,
    )


# 하위 호환: 기존 load_config 사용처를 위해 doctor-only loader 도 유지
@dataclass
class DoctorOnlyConfig:
    enabled: bool = True
    known_user_aliases: dict[str, str] = field(default_factory=dict)
    scan_targets: list[str] = field(default_factory=lambda: list(DEFAULT_SCAN_TARGETS))
    severity_overrides: dict[str, str] = field(default_factory=dict)


def load_config(path: Path | None = None) -> DoctorOnlyConfig:
    """doctor 모듈 호환용 wrapper. 신규 코드는 load_anvyc_config 사용 권장."""
    cfg = load_anvyc_config(path)
    return DoctorOnlyConfig(
        enabled=cfg.doctor.enabled,
        known_user_aliases=cfg.doctor.known_user_aliases,
        scan_targets=cfg.doctor.scan_targets,
        severity_overrides=cfg.doctor.severity_overrides,
    )


def build_check_context(cfg: DoctorOnlyConfig | DoctorConfig) -> CheckContext:
    """DoctorConfig → CheckContext 변환 (~ 확장 포함)."""
    return CheckContext(
        current_user=getpass.getuser(),
        known_user_aliases=cfg.known_user_aliases,
        scan_targets=[Path(p).expanduser() for p in cfg.scan_targets],
    )
