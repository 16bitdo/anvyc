"""tools configure 의 순수 선택 모델 + 안전 yaml writer (PR3).

TUI(view, 후속 PR)·CLI 와 분리된 로직 SoT. 다음을 책임진다:

- `collect_tool_rows` — tools list / MCP tools_list / configure 가 공유하는 row 빌더
  (런타임 상태 + AdapterMeta). cli._collect_tools_rows 가 이 함수에 위임한다.
- `collect_choices` / `apply_toggles` / `plan_changes` — 선택 상태를 순수 함수로 다룸.
- `apply_enabled` — `tools.<name>.enabled` 만 갱신하고 나머지 섹션
  (storage/security/secrets/cost/doctor/project_roots)·각 tool 의 다른 키
  (files/include/exclude/extra)는 보존. 쓰기 전 `.bak` 백업 + atomic replace.

anvyc 불변식: 값(secret) 미접촉 — 이 모듈은 enabled 토글만 다룬다.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from anvyc.core.yaml_io import atomic_write_yaml

# file path 만 생성자로 받는 adapter (cli._collect_tools_rows 와 동일 집합).
_FILE_CTOR_ADAPTERS = {"shell", "git", "aws", "gh", "pulumi"}


def collect_tool_rows(config: Path | None) -> list[dict[str, Any]]:
    """tools list / MCP tools_list / configure 의 row 데이터 (단일 SoT).

    각 row 는 런타임 상태(enabled / detected / files / secrets)와 AdapterMeta 정적
    메타(label / category / summary / includes / excludes / default_enabled /
    config_kind / since)를 함께 담는다. 기존 키(tool/enabled/detected/files/secrets)는
    하위호환을 위해 유지한다.
    """
    from anvyc.core.backup import ADAPTERS
    from anvyc.core.config import load_anvyc_config

    cfg = load_anvyc_config(config) if config else load_anvyc_config()
    rows: list[dict[str, Any]] = []
    for name, cls in ADAPTERS.items():
        meta = cls.meta
        tool_cfg = cfg.tools.get(name)
        enabled = tool_cfg.enabled if tool_cfg else True
        files_count = 0
        secrets_count = 0
        if tool_cfg is not None:
            files_count = len(tool_cfg.files) + len(tool_cfg.include)
            secrets_count = len(tool_cfg.secret_files)
        try:
            if name in _FILE_CTOR_ADAPTERS:
                files_arg = tuple(tool_cfg.files) if tool_cfg and tool_cfg.files else ()
                adapter = cls(files=files_arg)  # type: ignore[call-arg]
            else:
                adapter = cls()
            detected = adapter.detect()
        except Exception:
            detected = False
        rows.append(
            {
                "tool": name,
                "label": meta.label,
                "category": meta.category,
                "summary": meta.summary,
                "enabled": enabled,
                "detected": detected,
                "files": files_count,
                "secrets": secrets_count,
                "includes": list(meta.includes),
                "excludes": list(meta.excludes),
                "default_enabled": meta.default_enabled,
                "config_kind": meta.config_kind,
                "since": meta.since,
            }
        )
    return rows


@dataclass(frozen=True)
class ToolChoice:
    """configure 화면의 도구 1행 — 초기 선택 상태(effective enabled) + 표시용 메타."""

    name: str
    label: str
    category: str
    summary: str
    enabled: bool
    detected: bool
    default_enabled: bool


@dataclass(frozen=True)
class EnabledChange:
    name: str
    before: bool
    after: bool


@dataclass
class ConfigureResult:
    changes: list[EnabledChange]
    written: bool
    config_path: Path
    backup_path: Path | None


def collect_choices(config: Path | None = None) -> list[ToolChoice]:
    """현재 config 기준 도구별 초기 선택 상태 + 메타 + 감지 (collect_tool_rows 위임)."""
    return [
        ToolChoice(
            name=r["tool"],
            label=r["label"],
            category=r["category"],
            summary=r["summary"],
            enabled=bool(r["enabled"]),
            detected=bool(r["detected"]),
            default_enabled=bool(r["default_enabled"]),
        )
        for r in collect_tool_rows(config)
    ]


def render_supported_tools_markdown() -> str:
    """README §4 '지원 도구' 표를 AdapterMeta SoT 에서 생성 (scripts/gen_supported_tools.py).

    런타임 상태(detect/config)와 무관한 정적 메타만 사용 → 어느 환경에서 돌려도 동일.
    표 순서는 ADAPTERS 레지스트리 순서.
    """
    from anvyc.core.backup import ADAPTERS

    lines = [
        "| 도구 | 분류 | 기본 포함 | 기본 제외 | 도입 |",
        "|---|---|---|---|---|",
    ]
    for cls in ADAPTERS.values():
        m = cls.meta
        inc = ", ".join(f"`{x}`" for x in m.includes) or "—"
        exc = ", ".join(f"`{x}`" for x in m.excludes) or "—"
        lines.append(f"| {m.label} | {m.category} | {inc} | {exc} | {m.since} |")
    return "\n".join(lines)


def apply_toggles(choices: list[ToolChoice], indices: Iterable[int]) -> dict[str, bool]:
    """1-based 번호 집합을 토글한 뒤 전체 도구의 name→enabled 맵을 반환 (순수)."""
    idx = set(indices)
    return {
        c.name: (not c.enabled) if (i in idx) else c.enabled
        for i, c in enumerate(choices, start=1)
    }


def plan_changes(
    choices: list[ToolChoice], targets: dict[str, bool]
) -> list[EnabledChange]:
    """선택 상태(choices) 대비 targets 의 enabled 차이만 추려 반환 (순수)."""
    before = {c.name: c.enabled for c in choices}
    return [
        EnabledChange(name, before[name], after)
        for name, after in targets.items()
        if name in before and before[name] != after
    ]


def apply_enabled(
    config_path: Path, targets: dict[str, bool], *, make_backup: bool = True
) -> ConfigureResult:
    """targets(name→enabled) 를 anvyc.yaml 에 반영. 변경된 항목만 수정.

    - 다른 섹션·다른 tool 키·각 tool 의 다른 설정 키는 보존.
    - 변경이 없으면 파일을 건드리지 않는다(written=False, .bak 미생성).
    - 쓰기 전 원본을 `<name>.bak` 으로 복사 + atomic replace.

    주의: PyYAML 기반이라 재작성 시 주석/포맷은 보존되지 않는다 — 복구는 `.bak`.
    """
    if not config_path.is_file():
        raise FileNotFoundError(config_path)

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw: dict[str, Any] = loaded if isinstance(loaded, dict) else {}
    orig_tools = raw.get("tools")
    orig_tools = orig_tools if isinstance(orig_tools, dict) else {}

    def _before(name: str) -> bool:
        entry = orig_tools.get(name)
        if isinstance(entry, dict) and "enabled" in entry:
            return bool(entry["enabled"])
        return True  # 미정의 = effective enabled (collect_tool_rows 와 동일)

    changes = [
        EnabledChange(name, _before(name), bool(after))
        for name, after in targets.items()
        if _before(name) != bool(after)
    ]
    if not changes:
        return ConfigureResult([], written=False, config_path=config_path, backup_path=None)

    tools_dict: dict[str, Any] = dict(orig_tools)
    for ch in changes:
        entry = tools_dict.get(ch.name)
        new_entry = dict(entry) if isinstance(entry, dict) else {}
        new_entry["enabled"] = ch.after
        tools_dict[ch.name] = new_entry
    raw["tools"] = tools_dict

    backup_path: Path | None = None
    if make_backup:
        backup_path = config_path.with_name(config_path.name + ".bak")
        backup_path.write_bytes(config_path.read_bytes())

    atomic_write_yaml(raw, config_path)
    return ConfigureResult(changes, written=True, config_path=config_path, backup_path=backup_path)
