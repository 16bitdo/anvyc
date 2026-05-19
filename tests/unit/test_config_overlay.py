"""multi-host overlay (anvyc.<hostname>.yaml) — v0.6.4.

ANVYC_HOSTNAME env override 로 hostname 고정. 외부 hostname 의존 없음.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from anvyc.core.config import _deep_merge, load_anvyc_config


# ----- _deep_merge unit ---------------------------------------------------


def test_deep_merge_dict_recurse() -> None:
    base = {"a": {"b": 1, "c": 2}}
    overlay = {"a": {"c": 99, "d": 4}}
    out = _deep_merge(base, overlay)
    assert out == {"a": {"b": 1, "c": 99, "d": 4}}


def test_deep_merge_list_overlay_replaces_base() -> None:
    """안전성 위해 list 는 concat 아니라 overlay 가 대체."""
    base = {"items": [1, 2, 3]}
    overlay = {"items": [9]}
    out = _deep_merge(base, overlay)
    assert out == {"items": [9]}


def test_deep_merge_scalar_overlay_wins() -> None:
    base = {"flag": True, "name": "base"}
    overlay = {"flag": False}
    out = _deep_merge(base, overlay)
    assert out == {"flag": False, "name": "base"}


# ----- load_anvyc_config + overlay integration ---------------------------


@pytest.fixture
def yaml_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """isolation: ANVYC_HOSTNAME fixed + clean .anvyc/ dir."""
    d = tmp_path / ".anvyc"
    d.mkdir()
    monkeypatch.setenv("ANVYC_HOSTNAME", "test-host")
    return d


def _write(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body))


def test_no_overlay_returns_base_only(yaml_dir: Path) -> None:
    base = yaml_dir / "anvyc.yaml"
    _write(
        base,
        """\
        version: 1
        security:
          secret_scan: true
        """,
    )

    cfg = load_anvyc_config(base)
    assert cfg.source == base
    assert cfg.overlay_source is None
    assert cfg.security.secret_scan is True


def test_overlay_scalar_override(yaml_dir: Path) -> None:
    """overlay 의 scalar 가 base 를 대체."""
    base = yaml_dir / "anvyc.yaml"
    overlay = yaml_dir / "anvyc.test-host.yaml"
    _write(
        base,
        """\
        version: 1
        security:
          secret_scan: true
          block_on_secret: true
        """,
    )
    _write(
        overlay,
        """\
        security:
          secret_scan: false
        """,
    )

    cfg = load_anvyc_config(base)
    assert cfg.overlay_source == overlay
    assert cfg.security.secret_scan is False
    # base 의 block_on_secret 는 유지 (dict deep merge)
    assert cfg.security.block_on_secret is True


def test_overlay_tools_deep_merge(yaml_dir: Path) -> None:
    """overlay 의 tools 키가 base.tools 와 deep merge."""
    base = yaml_dir / "anvyc.yaml"
    overlay = yaml_dir / "anvyc.test-host.yaml"
    _write(
        base,
        """\
        tools:
          shell:
            enabled: true
            files:
              - "/base/zshrc"
          git:
            enabled: true
        """,
    )
    _write(
        overlay,
        """\
        tools:
          git:
            enabled: false
        """,
    )

    cfg = load_anvyc_config(base)
    assert cfg.overlay_source == overlay
    # shell 유지
    assert cfg.tools["shell"].enabled is True
    assert cfg.tools["shell"].files == ["/base/zshrc"]
    # git overlay 적용
    assert cfg.tools["git"].enabled is False


def test_overlay_list_replaces_base(yaml_dir: Path) -> None:
    """list 는 overlay 가 대체 (concat 아님)."""
    base = yaml_dir / "anvyc.yaml"
    overlay = yaml_dir / "anvyc.test-host.yaml"
    _write(
        base,
        """\
        tools:
          shell:
            files:
              - "/base/a"
              - "/base/b"
        """,
    )
    _write(
        overlay,
        """\
        tools:
          shell:
            files:
              - "/overlay/c"
        """,
    )

    cfg = load_anvyc_config(base)
    assert cfg.tools["shell"].files == ["/overlay/c"]


def test_anvyc_hostname_env_drives_overlay_filename(
    yaml_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ANVYC_HOSTNAME=foo → anvyc.foo.yaml 사용, anvyc.bar.yaml 무시."""
    base = yaml_dir / "anvyc.yaml"
    foo_overlay = yaml_dir / "anvyc.foo.yaml"
    bar_overlay = yaml_dir / "anvyc.bar.yaml"
    _write(base, "security:\n  secret_scan: true\n")
    _write(foo_overlay, "security:\n  secret_scan: false\n")
    _write(bar_overlay, "security:\n  secret_scan: true\n  block_on_secret: false\n")

    monkeypatch.setenv("ANVYC_HOSTNAME", "foo")
    cfg = load_anvyc_config(base)
    assert cfg.overlay_source == foo_overlay
    assert cfg.security.secret_scan is False
    assert cfg.security.block_on_secret is True  # bar overlay 무시


def test_overlay_absent_silently_skipped(yaml_dir: Path) -> None:
    """overlay file 부재 → overlay_source None, base 그대로."""
    base = yaml_dir / "anvyc.yaml"
    _write(base, "security:\n  secret_scan: true\n")

    cfg = load_anvyc_config(base)
    assert cfg.overlay_source is None
    assert cfg.security.secret_scan is True
