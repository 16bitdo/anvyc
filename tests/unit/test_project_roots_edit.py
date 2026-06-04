"""core.project_roots_edit — roots 변경 순수 로직 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core.project_roots import DEFAULT_PROJECT_ROOTS
from anvyc.core.project_roots_edit import _current_explicit_roots, _load_raw, normalize_root


def test_normalize_keeps_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("~/dev") == "~/dev"


def test_normalize_contracts_home_abs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("/Users/tester/work") == "~/work"
    assert normalize_root("/Users/tester") == "~"


def test_normalize_strips_trailing_slash_and_space(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("  ~/dev/  ") == "~/dev"


def test_normalize_keeps_non_home_abs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("/opt/projects") == "/opt/projects"


def test_normalize_empty_returns_empty() -> None:
    assert normalize_root("   ") == ""


# ---------------------------------------------------------------------------
# Task 3: _load_raw + _current_explicit_roots
# ---------------------------------------------------------------------------


def test_load_raw_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _load_raw(tmp_path / "nope.yaml") == {}


def test_current_roots_explicit(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/work\n  - ~/side\n")
    roots, was_explicit = _current_explicit_roots(_load_raw(cfg))
    assert roots == ["~/work", "~/side"]
    assert was_explicit is True


def test_current_roots_materializes_default(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")  # project_roots 없음
    roots, was_explicit = _current_explicit_roots(_load_raw(cfg))
    assert roots == list(DEFAULT_PROJECT_ROOTS)
    assert was_explicit is False


def test_current_roots_empty_list_materializes(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots: []\n")
    roots, was_explicit = _current_explicit_roots(_load_raw(cfg))
    assert roots == list(DEFAULT_PROJECT_ROOTS)
    assert was_explicit is False
