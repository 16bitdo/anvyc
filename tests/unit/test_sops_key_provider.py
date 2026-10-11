from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch

from anvyc.checks.base import CheckContext
from anvyc.checks.sops_keys import SopsKeysCheck
from anvyc.core.config import build_check_context, load_anvyc_config, load_config
from anvyc.core.sops import decrypt


def clean_context(tmp_path, monkeypatch):
    for name in ("SOPS_AGE_KEY", "SOPS_AGE_KEY_FILE", "SOPS_AGE_KEY_CMD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("anvyc.checks.sops_keys.is_available", lambda _: True)
    return CheckContext(sops_identity_file=str(tmp_path / "absent"))


def test_configured_provider_reaches_doctor(tmp_path, monkeypatch):
    clean_context(tmp_path, monkeypatch)
    cfg=tmp_path / "anvyc.yaml"
    cfg.write_text(f"security:\n  sops:\n    age_identity_file: {tmp_path}/absent\n    age_key_cmd: {sys.executable} -c pass\n")
    assert load_anvyc_config(cfg).security.sops.age_key_cmd == f"{sys.executable} -c pass"
    ctx=build_check_context(load_config(cfg))
    with patch("subprocess.run", side_effect=AssertionError("doctor must not fetch secrets")):
        assert SopsKeysCheck().run(ctx) == []


def test_environment_provider_supported(tmp_path, monkeypatch):
    ctx=clean_context(tmp_path, monkeypatch)
    monkeypatch.setenv("SOPS_AGE_KEY_CMD", sys.executable + " -c pass")
    assert SopsKeysCheck().run(ctx) == []


def test_missing_or_malformed_provider_warns(tmp_path, monkeypatch):
    ctx=clean_context(tmp_path, monkeypatch)
    for command in ("/missing/anvyc-op", "'invalid"):
        ctx.sops_key_cmd=command
        results=SopsKeysCheck().run(ctx)
        assert results and all(x.severity.is_blocking for x in results)


def test_custom_identity_and_directory(tmp_path, monkeypatch):
    ctx=clean_context(tmp_path, monkeypatch)
    custom=tmp_path / "identity"
    custom.write_text("# discovery fixture, never used for crypto\n")
    ctx.sops_identity_file=str(custom)
    assert SopsKeysCheck().run(ctx) == []
    ctx.sops_identity_file=str(tmp_path)
    assert SopsKeysCheck().run(ctx)


def test_decrypt_passes_configured_command_only_to_child(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPS_AGE_KEY_CMD", "old-command")
    source=tmp_path / "cipher.sops.json"
    source.write_text("{}")
    with patch("anvyc.core.sops.sops_available", return_value=True), patch(
        "anvyc.core.sops.subprocess.run", return_value=subprocess.CompletedProcess([],0,"","")
    ) as run:
        decrypt(source, tmp_path / "plain", key_cmd="op read op://Private/item/credential")
    assert run.call_args.kwargs["env"]["SOPS_AGE_KEY_CMD"] == "op read op://Private/item/credential"
    assert os.environ["SOPS_AGE_KEY_CMD"] == "old-command"
