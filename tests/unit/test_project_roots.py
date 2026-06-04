"""project_roots SoT 모듈 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core.config import AnvycConfig, load_anvyc_config
from anvyc.core.project_roots import DEFAULT_PROJECT_ROOTS, resolve_project_roots


def test_default_roots_dev_first() -> None:
    """DEFAULT_PROJECT_ROOTS 는 ~/dev 를 선두로 한 6-루트, ~/Documents 는 제외(deprecated)."""
    assert DEFAULT_PROJECT_ROOTS[0] == "~/dev"
    assert len(DEFAULT_PROJECT_ROOTS) == 6
    assert "~/Documents" not in DEFAULT_PROJECT_ROOTS


def test_resolve_load_failure_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """config=None 이고 load_anvyc_config 가 실패하면 DEFAULT 로 fallback."""

    def _raise(*_a: object, **_k: object) -> AnvycConfig:
        raise RuntimeError("boom")

    monkeypatch.setattr("anvyc.core.config.load_anvyc_config", _raise)
    assert resolve_project_roots() == DEFAULT_PROJECT_ROOTS


def test_resolve_config_with_roots() -> None:
    """project_roots 가 채워지면 그 값을 그대로 반환."""
    cfg = AnvycConfig(project_roots=["~/work", "~/x"])
    assert resolve_project_roots(cfg) == ("~/work", "~/x")


def test_resolve_empty_roots_fallback() -> None:
    """project_roots: [] 는 DEFAULT 로 fallback."""
    cfg = AnvycConfig(project_roots=[])
    assert resolve_project_roots(cfg) == DEFAULT_PROJECT_ROOTS


def test_resolve_strips_blank_entries() -> None:
    """공백/빈 문자열 항목은 strip·제거된다."""
    cfg = AnvycConfig(project_roots=["  ~/work  ", "", "  "])
    assert resolve_project_roots(cfg) == ("~/work",)


def test_load_config_parses_project_roots(tmp_path: Path) -> None:
    """anvyc.yaml 의 top-level project_roots 가 AnvycConfig 로 파싱된다."""
    cfg_file = tmp_path / "anvyc.yaml"
    cfg_file.write_text("project_roots:\n  - ~/work\n  - ~/side\n")
    cfg = load_anvyc_config(cfg_file)
    assert cfg.project_roots == ["~/work", "~/side"]


def test_load_config_no_project_roots(tmp_path: Path) -> None:
    """project_roots 미지정 시 빈 리스트."""
    cfg_file = tmp_path / "anvyc.yaml"
    cfg_file.write_text("storage:\n  root: .anvyc\n")
    cfg = load_anvyc_config(cfg_file)
    assert cfg.project_roots == []
