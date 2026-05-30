"""anvyc.yaml `doctor.creds_expiry.warn_thresholds` 파싱 + CheckContext 흐름 (CP-5)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from anvyc.core.config import build_check_context, load_anvyc_config, load_config


@pytest.fixture
def yaml_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / ".anvyc"
    d.mkdir()
    monkeypatch.setenv("ANVYC_HOSTNAME", "test-host")
    return d


def _write(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body))


def test_creds_thresholds_absent_default_empty(yaml_dir: Path) -> None:
    base = yaml_dir / "anvyc.yaml"
    _write(base, "version: 1\n")
    assert load_anvyc_config(base).doctor.creds_warn_thresholds == {}


def test_creds_thresholds_parsed_and_flows_to_context(yaml_dir: Path) -> None:
    base = yaml_dir / "anvyc.yaml"
    _write(
        base,
        """\
        version: 1
        doctor:
          creds_expiry:
            warn_thresholds:
              aws_sso: 1800
              github: 259200
        """,
    )
    cfg = load_anvyc_config(base)
    assert cfg.doctor.creds_warn_thresholds == {"aws_sso": 1800.0, "github": 259200.0}
    # load_config(doctor wrapper) + build_check_context → CheckContext 까지 전달
    ctx = build_check_context(load_config(base))
    assert ctx.creds_warn_thresholds == {"aws_sso": 1800.0, "github": 259200.0}


def test_creds_thresholds_ignores_non_numeric(yaml_dir: Path) -> None:
    base = yaml_dir / "anvyc.yaml"
    _write(
        base,
        """\
        version: 1
        doctor:
          creds_expiry:
            warn_thresholds:
              aws_sso: 900
              bad: "nope"
        """,
    )
    assert load_anvyc_config(base).doctor.creds_warn_thresholds == {"aws_sso": 900.0}
