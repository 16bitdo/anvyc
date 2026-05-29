"""Unit tests for secret-registry-valid doctor check (CP-15 Phase 1)."""
from __future__ import annotations

from pathlib import Path

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.secret_registry import CHECK_NAME, SecretRegistryValidCheck


def _cfg(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "anvyc.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_check_silent_when_all_ok(tmp_path: Path) -> None:
    path = _cfg(
        tmp_path,
        """
secrets:
  entries:
    - name: a
      backend: op
      ref: "op://v/i/f"
""",
    )
    results = SecretRegistryValidCheck(config_path=path).run(CheckContext())
    assert results == []


def test_check_warns_on_invalid_handle(tmp_path: Path) -> None:
    path = _cfg(
        tmp_path,
        """
secrets:
  entries:
    - name: a
      backend: op
""",
    )  # ref 누락 → invalid
    results = SecretRegistryValidCheck(config_path=path).run(CheckContext())
    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert results[0].check_name == CHECK_NAME


def test_check_info_on_unknown_backend(tmp_path: Path) -> None:
    path = _cfg(
        tmp_path,
        """
secrets:
  entries:
    - name: a
      backend: hashicorp-vault
""",
    )
    results = SecretRegistryValidCheck(config_path=path).run(CheckContext())
    assert len(results) == 1
    assert results[0].severity == Severity.INFO


def test_check_empty_when_no_secrets(tmp_path: Path) -> None:
    path = _cfg(tmp_path, "storage:\n  root: .anvyc\n")
    results = SecretRegistryValidCheck(config_path=path).run(CheckContext())
    assert results == []
