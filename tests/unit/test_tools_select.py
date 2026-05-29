"""core.tools_select 순수 선택 모델 + 안전 yaml writer 단위 테스트 (PR3)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from anvyc.core.tools_select import (
    ToolChoice,
    apply_enabled,
    apply_toggles,
    collect_choices,
    collect_tool_rows,
    plan_changes,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body))


def _choices(*specs: tuple[str, bool]) -> list[ToolChoice]:
    return [
        ToolChoice(
            name=n, label=n, category="x", summary="", enabled=e,
            detected=False, default_enabled=True,
        )
        for n, e in specs
    ]


def test_collect_tool_rows_has_meta_keys(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    _write(cfg, "version: 1\ntools: {}\n")
    rows = collect_tool_rows(cfg)
    assert len(rows) >= 9
    sample = next(r for r in rows if r["tool"] == "aws")
    for k in (
        "label", "category", "summary", "includes", "excludes",
        "default_enabled", "config_kind", "since",
        "enabled", "detected", "files", "secrets",
    ):
        assert k in sample, f"missing key: {k}"


def test_apply_toggles_flips_only_selected() -> None:
    choices = _choices(("a", True), ("b", False), ("c", True))
    assert apply_toggles(choices, [1, 2]) == {"a": False, "b": True, "c": True}


def test_apply_toggles_empty_is_noop() -> None:
    choices = _choices(("a", True), ("b", False))
    assert apply_toggles(choices, []) == {"a": True, "b": False}


def test_plan_changes_returns_only_diffs() -> None:
    choices = _choices(("a", True), ("b", False), ("c", True))
    changes = plan_changes(choices, {"a": False, "b": False, "c": True})
    assert len(changes) == 1
    assert changes[0].name == "a"
    assert changes[0].before is True
    assert changes[0].after is False


def test_apply_enabled_changed_only_and_preserves(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    _write(
        cfg,
        """\
        version: 1
        storage:
          keep_backups: 7
        security:
          secret_scan: true
        tools:
          shell:
            enabled: true
            files:
              - "~/.zshrc"
          git:
            enabled: true
        """,
    )
    result = apply_enabled(cfg, {"git": False, "shell": True})
    assert result.written is True
    assert {c.name for c in result.changes} == {"git"}
    assert result.backup_path is not None and result.backup_path.is_file()

    data = yaml.safe_load(cfg.read_text())
    assert data["tools"]["git"]["enabled"] is False
    # 보존: shell.files / storage / security / version
    assert data["tools"]["shell"]["files"] == ["~/.zshrc"]
    assert data["storage"]["keep_backups"] == 7
    assert data["security"]["secret_scan"] is True
    assert data["version"] == 1


def test_apply_enabled_adds_entry_for_absent_tool(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    _write(cfg, "version: 1\ntools: {}\n")
    result = apply_enabled(cfg, {"aws": False})  # absent → effective True → 변경
    assert result.written is True
    data = yaml.safe_load(cfg.read_text())
    assert data["tools"]["aws"]["enabled"] is False


def test_apply_enabled_noop_when_no_change(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    _write(cfg, "version: 1\ntools: {}\n")
    before = cfg.read_text()
    result = apply_enabled(cfg, {"aws": True})  # 이미 effective True
    assert result.written is False
    assert result.changes == []
    assert result.backup_path is None
    assert cfg.read_text() == before  # 파일 미변경
    assert not (tmp_path / "anvyc.yaml.bak").exists()


def test_apply_enabled_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        apply_enabled(tmp_path / "nope.yaml", {"aws": False})


def test_apply_enabled_no_backup_flag(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    _write(cfg, "version: 1\ntools: {}\n")
    result = apply_enabled(cfg, {"aws": False}, make_backup=False)
    assert result.written is True
    assert result.backup_path is None
    assert not (tmp_path / "anvyc.yaml.bak").exists()


def test_collect_choices_reflects_config(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    _write(cfg, "version: 1\ntools:\n  git: {enabled: false}\n")
    by = {c.name: c for c in collect_choices(cfg)}
    assert by["git"].enabled is False
    assert by["shell"].enabled is True  # 미정의 → effective True
