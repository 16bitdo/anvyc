"""anvyc.yaml 최소 로더.

전체 schema 검증은 후속 task (pydantic 모델). 현재는 backup/doctor 동작에 필요한 영역만.
파일이 없거나 키가 없는 경우 안전한 기본값을 반환한다.

v0.6.4: base `anvyc.yaml` 위에 같은 디렉터리의 `anvyc.<hostname>.yaml` overlay 가
존재하면 deep-merge 후 parsing. hostname 은 `socket.gethostname().split(".")[0]`
또는 `ANVYC_HOSTNAME` env 로 override.
"""
from __future__ import annotations

import getpass
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
class SecretFileSpec:
    """secret_files 의 단일 항목 — yaml 의 string 또는 {path, format} dict 형식 정규화.

    format=None 이면 tool/global 의 format chain 사용 (file > tool > global > default).
    """

    path: str
    format: str | None = None


def _normalize_secret_files(raw: object) -> list[SecretFileSpec]:
    """yaml 의 secret_files 값 (list of str 또는 list of dict) 을 SecretFileSpec 리스트로."""
    out: list[SecretFileSpec] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str):
            out.append(SecretFileSpec(path=item))
        elif isinstance(item, dict):
            path_v = item.get("path")
            if not path_v:
                # invalid entry — silently skip
                continue
            fmt = item.get("format")
            out.append(
                SecretFileSpec(
                    path=str(path_v),
                    format=str(fmt) if fmt else None,
                )
            )
        # 다른 타입은 무시
    return out


@dataclass
class ToolConfig:
    enabled: bool = True
    files: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    secret_files: list[SecretFileSpec] = field(default_factory=list)
    sops_format: str | None = None   # None 이면 전역 security.sops.format 사용
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DoctorConfig:
    enabled: bool = True
    known_user_aliases: dict[str, str] = field(default_factory=dict)
    scan_targets: list[str] = field(default_factory=lambda: list(DEFAULT_SCAN_TARGETS))
    severity_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class CostGithubConfig:
    """CP-13 GitHub adapter (PR-13D + polish CP-13H) 의 account override.

    빈 list 면 adapter 가 `~/.config/gh*` glob walk 으로 자동 discover. 명시 시
    discover 대체. 각 entry 는 `"<gh_login>"` (user-level) 또는
    `"<gh_login>@<org>"` (org-level) syntax — PR-13D account.key 인코딩 정합.
    """

    accounts: list[str] = field(default_factory=list)


@dataclass
class CostConfig:
    """CP-13 cost observability 의 통합 config section."""

    github: CostGithubConfig = field(default_factory=CostGithubConfig)


@dataclass
class SecretEntry:
    """secrets.entries 의 단일 항목 — CP-15 Secret Broker 레지스트리.

    값(secret 본문)은 담지 않는다. backend 별 "핸들" 만 보유 (op reference /
    sops file+key / keychain service+account / aws-vault profile).
    """

    name: str
    backend: str                          # op | sops | keychain | aws-vault
    ref: str | None = None                # backend=op  : op://<vault>/<item>/<field>
    file: str | None = None               # backend=sops: SOPS 파일 경로
    key: str | None = None                # backend=sops: inplace 모드의 dotted key (binary 면 생략)
    service: str | None = None            # backend=keychain
    account: str | None = None            # backend=keychain
    profile: str | None = None            # backend=aws-vault
    wire: dict[str, Any] = field(default_factory=dict)  # (선택) JIT 주입 와이어링 (Phase 2.5)


@dataclass
class SecretsConfig:
    """CP-15 `secrets:` 블록 — reference 레지스트리 + 조회 sink 기본값."""

    schema_version: int = 1
    default_sink: str = "clipboard"       # clipboard | reveal — get 기본 동작 (Phase 2)
    clipboard_clear_seconds: int = 20
    entries: list[SecretEntry] = field(default_factory=list)


def _normalize_secret_entries(raw: object) -> list[SecretEntry]:
    """yaml 의 secrets.entries (list of dict) 를 SecretEntry 리스트로.

    name 또는 backend 가 없는 항목은 silently skip (graceful — CP-13 §2.1 패턴).
    """
    out: list[SecretEntry] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        backend = item.get("backend")
        if not name or not backend:
            continue
        wire = item.get("wire")
        out.append(
            SecretEntry(
                name=str(name),
                backend=str(backend),
                ref=str(item["ref"]) if item.get("ref") else None,
                file=str(item["file"]) if item.get("file") else None,
                key=str(item["key"]) if item.get("key") else None,
                service=str(item["service"]) if item.get("service") else None,
                account=str(item["account"]) if item.get("account") else None,
                profile=str(item["profile"]) if item.get("profile") else None,
                wire=dict(wire) if isinstance(wire, dict) else {},
            )
        )
    return out


@dataclass
class AnvycConfig:
    storage: StorageConfig = field(default_factory=StorageConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    tools: dict[str, ToolConfig] = field(default_factory=dict)
    doctor: DoctorConfig = field(default_factory=DoctorConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    secrets: SecretsConfig = field(default_factory=SecretsConfig)
    project_roots: list[str] = field(default_factory=list)  # 빈 리스트면 SoT DEFAULT
    source: Path | None = None  # 로드된 base yaml 경로 (debug 용)
    overlay_source: Path | None = None  # v0.6.4 — 적용된 host overlay 경로 (debug 용)


def _read_yaml(path: Path) -> dict[str, Any]:
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


def _hostname_short() -> str:
    """ANVYC_HOSTNAME env override 또는 socket.gethostname() short part (FQDN 안전)."""
    h = os.environ.get("ANVYC_HOSTNAME") or socket.gethostname()
    return h.split(".")[0]


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """base 위에 overlay 적용 (recursive).

    - dict + dict: recursive merge
    - list: overlay 가 대체 (concat 아님 — 안전성/명시성)
    - scalar: overlay 우선
    """
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _resolve_overlay(base: Path) -> Path | None:
    """base 와 같은 디렉터리의 anvyc.<hostname>.yaml. 없으면 None."""
    overlay = base.parent / f"anvyc.{_hostname_short()}.yaml"
    return overlay if overlay.is_file() else None


def load_anvyc_config(path: Path | None = None) -> AnvycConfig:
    """anvyc.yaml 전체를 읽어 AnvycConfig 로 반환. 없으면 기본값.

    base 발견 시 같은 디렉터리의 `anvyc.<hostname>.yaml` overlay 가 있으면
    deep-merge 후 parsing (v0.6.4).
    """
    raw: dict[str, Any] = {}
    source: Path | None = None
    overlay_source: Path | None = None
    for c in _candidate_paths(path):
        if c.exists() and c.is_file():
            raw = _read_yaml(c)
            source = c
            break

    if source is not None:
        overlay_path = _resolve_overlay(source)
        if overlay_path is not None:
            overlay_raw = _read_yaml(overlay_path)
            if overlay_raw:
                raw = _deep_merge(raw, overlay_raw)
                overlay_source = overlay_path

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
            secret_files=_normalize_secret_files(body.get("secret_files")),
            sops_format=str(sops_format_raw) if sops_format_raw else None,
            extra=extra,
        )

    doctor_raw = raw.get("doctor") or {}
    cu = doctor_raw.get("cross_user") or {}
    doctor = DoctorConfig(
        enabled=bool(cu.get("enabled", True)),
        known_user_aliases=dict(cu.get("known_user_aliases") or {}),
        scan_targets=list(cu.get("scan_targets") or DEFAULT_SCAN_TARGETS),
        severity_overrides=dict(cu.get("severity_overrides") or {}),
    )

    cost_raw = raw.get("cost") or {}
    cost_gh_raw = cost_raw.get("github") or {}
    cost = CostConfig(
        github=CostGithubConfig(
            accounts=[
                str(a) for a in (cost_gh_raw.get("accounts") or [])
                if isinstance(a, str)
            ],
        ),
    )

    secrets_raw = raw.get("secrets") or {}
    get_raw = secrets_raw.get("get") or {}
    secrets = SecretsConfig(
        schema_version=int(secrets_raw.get("schema_version") or 1),
        default_sink=str(get_raw.get("default_sink") or "clipboard"),
        clipboard_clear_seconds=int(get_raw.get("clipboard_clear_seconds") or 20),
        entries=_normalize_secret_entries(secrets_raw.get("entries")),
    )

    return AnvycConfig(
        storage=storage,
        security=security,
        tools=tools,
        doctor=doctor,
        cost=cost,
        secrets=secrets,
        project_roots=list(raw.get("project_roots") or []),
        source=source,
        overlay_source=overlay_source,
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
