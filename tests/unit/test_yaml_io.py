"""core.yaml_io — atomic YAML writer 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import yaml

from anvyc.core.yaml_io import atomic_write_yaml


def test_atomic_write_creates_parent_and_roundtrips(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "anvyc.yaml"
    atomic_write_yaml({"project_roots": ["~/dev", "~/work"]}, target)
    assert target.is_file()
    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert loaded == {"project_roots": ["~/dev", "~/work"]}


def test_atomic_write_overwrites_and_no_tmp_left(tmp_path: Path) -> None:
    target = tmp_path / "anvyc.yaml"
    target.write_text("old: 1\n", encoding="utf-8")
    atomic_write_yaml({"new": 2}, target)
    assert yaml.safe_load(target.read_text()) == {"new": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["anvyc.yaml"]
