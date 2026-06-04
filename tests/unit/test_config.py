"""AnvycConfig 파싱 단위 테스트."""
from __future__ import annotations

from pathlib import Path

from anvyc.core.config import AnvycConfig, load_anvyc_config


def test_config_parses_projects_and_excludes(tmp_path: Path) -> None:
    cfg_file = tmp_path / "anvyc.yaml"
    cfg_file.write_text(
        "projects:\n  - ~/work/x\nexclude_projects:\n  - ~/dev/archived\n"
    )
    cfg = load_anvyc_config(cfg_file)
    assert cfg.projects == ["~/work/x"]
    assert cfg.exclude_projects == ["~/dev/archived"]


def test_config_defaults_projects_empty() -> None:
    cfg = AnvycConfig()
    assert cfg.projects == [] and cfg.exclude_projects == []
