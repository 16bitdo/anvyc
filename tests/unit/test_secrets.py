"""Unit tests for anvyc.core.secrets + config secrets parsing (CP-15 Phase 1)."""
from __future__ import annotations

from pathlib import Path

from anvyc.core.config import SecretEntry, load_anvyc_config
from anvyc.core.secrets import (
    BACKEND_AWS_VAULT,
    BACKEND_KEYCHAIN,
    BACKEND_OP,
    BACKEND_SOPS,
    SCHEMA_VERSION,
    STATUS_INVALID,
    STATUS_OK,
    STATUS_UNKNOWN,
    collect_secrets,
    reference_of,
    verify_entry,
)


def _write_cfg(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "anvyc.yaml"
    p.write_text(body, encoding="utf-8")
    return p


# ---- config parsing ----

def test_config_parses_secrets_block(tmp_path: Path) -> None:
    cfg = load_anvyc_config(
        _write_cfg(
            tmp_path,
            """
secrets:
  schema_version: 1
  get:
    default_sink: clipboard
    clipboard_clear_seconds: 30
  entries:
    - name: AWS_ACCESS_KEY_ID
      backend: op
      ref: "op://Personal/AWS/access_key_id"
    - name: pulumi/passphrase
      backend: sops
      file: "~/.pulumi/creds.json"
      key: passphrase
""",
        )
    )
    assert cfg.secrets.schema_version == 1
    assert cfg.secrets.clipboard_clear_seconds == 30
    assert len(cfg.secrets.entries) == 2
    e0 = cfg.secrets.entries[0]
    assert e0.name == "AWS_ACCESS_KEY_ID"
    assert e0.backend == "op"
    assert e0.ref == "op://Personal/AWS/access_key_id"
    assert cfg.secrets.entries[1].key == "passphrase"


def test_config_secrets_default_empty(tmp_path: Path) -> None:
    cfg = load_anvyc_config(_write_cfg(tmp_path, "storage:\n  root: .anvyc\n"))
    assert cfg.secrets.entries == []
    assert cfg.secrets.default_sink == "clipboard"
    assert cfg.secrets.clipboard_clear_seconds == 20


def test_config_secrets_skips_incomplete_entries(tmp_path: Path) -> None:
    cfg = load_anvyc_config(
        _write_cfg(
            tmp_path,
            """
secrets:
  entries:
    - name: ok
      backend: op
      ref: "op://v/i/f"
    - backend: op            # name 없음 → skip
    - name: noback           # backend 없음 → skip
""",
        )
    )
    assert [e.name for e in cfg.secrets.entries] == ["ok"]


# ---- reference_of / verify_entry (probe-independent) ----

def test_reference_of_per_backend() -> None:
    assert reference_of(SecretEntry("x", BACKEND_OP, ref="op://v/i/f")) == "op://v/i/f"
    assert (
        reference_of(SecretEntry("x", BACKEND_SOPS, file="~/c.json", key="pw"))
        == "sops:~/c.json#pw"
    )
    assert (
        reference_of(SecretEntry("x", BACKEND_KEYCHAIN, service="s", account="a"))
        == "keychain:s/a"
    )
    assert reference_of(SecretEntry("x", BACKEND_AWS_VAULT, profile="prd")) == "aws-vault:prd"


def test_verify_entry_unknown_backend() -> None:
    s = verify_entry(SecretEntry("x", "hashicorp-vault"), probe=False)
    assert s.status == STATUS_UNKNOWN


def test_verify_entry_invalid_missing_handle() -> None:
    assert verify_entry(SecretEntry("x", BACKEND_OP), probe=False).status == STATUS_INVALID
    assert verify_entry(SecretEntry("x", BACKEND_SOPS), probe=False).status == STATUS_INVALID
    assert (
        verify_entry(SecretEntry("x", BACKEND_KEYCHAIN, service="s"), probe=False).status
        == STATUS_INVALID
    )
    assert verify_entry(SecretEntry("x", BACKEND_AWS_VAULT), probe=False).status == STATUS_INVALID


def test_verify_entry_ok_probe_false() -> None:
    s = verify_entry(SecretEntry("x", BACKEND_OP, ref="op://v/i/f"), probe=False)
    assert s.status == STATUS_OK
    assert s.reference == "op://v/i/f"


# ---- collect_secrets envelope ----

def test_collect_secrets_schema_and_keys(tmp_path: Path) -> None:
    cfg = load_anvyc_config(
        _write_cfg(
            tmp_path,
            """
secrets:
  entries:
    - name: a
      backend: op
      ref: "op://v/i/f"
    - name: b
      backend: bogus
""",
        )
    )
    report = collect_secrets(cfg=cfg, probe=False)
    assert report.schema_version == SCHEMA_VERSION
    d = report.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION
    assert isinstance(d["entries"], list)
    assert len(d["entries"]) == 2
    entry = d["entries"][0]
    assert isinstance(entry, dict)
    assert set(entry.keys()) == {"name", "backend", "reference", "status", "detail"}
    statuses = {e["name"]: e["status"] for e in d["entries"]}
    assert statuses["a"] == STATUS_OK
    assert statuses["b"] == STATUS_UNKNOWN
