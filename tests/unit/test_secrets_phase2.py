"""Unit tests for CP-15 Phase 2 — secret add/get core logic (anvyc.core.secrets)."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core.config import SecretEntry, load_anvyc_config
from anvyc.core.secrets import (
    BACKEND_OP,
    BACKEND_SOPS,
    SecretAddError,
    SecretGetError,
    _entry_to_dict,
    execute_add,
    get_entry_by_name,
    plan_add,
    register_entry,
    resolve_command,
)


def _seed_cfg(tmp_path: Path, body: str = "storage:\n  root: .anvyc\n") -> Path:
    p = tmp_path / "anvyc.yaml"
    p.write_text(body, encoding="utf-8")
    return p


# ---- plan_add (pure) ----

def test_plan_add_op_generate_constructs_ref() -> None:
    plan = plan_add("API_KEY", "op", generate=True, vault="Personal")
    assert plan.entry.ref == "op://Personal/API_KEY/password"
    assert plan.command[:3] == ["op", "item", "create"]
    assert "--generate-password=letters,digits,symbols,32" in plan.command
    assert "--vault=Personal" in plan.command


def test_plan_add_op_generate_title_override() -> None:
    plan = plan_add("svc/key", "op", generate=True, vault="Work", title="svc-key")
    assert plan.entry.ref == "op://Work/svc-key/password"


def test_plan_add_op_generate_requires_vault() -> None:
    with pytest.raises(SecretAddError):
        plan_add("k", "op", generate=True)


def test_plan_add_op_ref_register_only() -> None:
    plan = plan_add("AWS", "op", ref="op://Personal/AWS/key")
    assert plan.entry.ref == "op://Personal/AWS/key"
    assert plan.command == []  # 실행할 backend 명령 없음 — 등록만


def test_plan_add_op_requires_generate_or_ref() -> None:
    with pytest.raises(SecretAddError):
        plan_add("k", "op")


def test_plan_add_op_generate_ref_conflict() -> None:
    with pytest.raises(SecretAddError):
        plan_add("k", "op", generate=True, vault="V", ref="op://a/b/c")


def test_plan_add_sops() -> None:
    plan = plan_add("pw", "sops", file="~/.pulumi/creds.json", key="passphrase")
    assert plan.entry.backend == BACKEND_SOPS
    assert plan.entry.file == "~/.pulumi/creds.json"
    assert plan.entry.key == "passphrase"
    assert plan.command[:2] == ["sops", "edit"]


def test_plan_add_sops_requires_file() -> None:
    with pytest.raises(SecretAddError):
        plan_add("pw", "sops")


def test_plan_add_unsupported_backend() -> None:
    with pytest.raises(SecretAddError):
        plan_add("k", "hashicorp-vault")


# ---- _entry_to_dict / execute_add ----

def test_entry_to_dict_omits_none_fields() -> None:
    d = _entry_to_dict(SecretEntry("AWS", BACKEND_OP, ref="op://a/b/c"))
    assert d == {"name": "AWS", "backend": "op", "ref": "op://a/b/c"}


def test_execute_add_empty_command_is_noop() -> None:
    assert execute_add([]) == 0


# ---- register_entry (yaml round-trip) ----

def test_register_entry_appends_and_backs_up(tmp_path: Path) -> None:
    path = _seed_cfg(tmp_path)
    target = register_entry(
        SecretEntry("AWS", BACKEND_OP, ref="op://Personal/AWS/key"), config_path=path
    )
    assert target == path
    cfg = load_anvyc_config(path)
    assert [e.name for e in cfg.secrets.entries] == ["AWS"]
    assert cfg.secrets.entries[0].ref == "op://Personal/AWS/key"
    assert len(list(tmp_path.glob("anvyc.yaml.bak-*"))) == 1


def test_register_entry_preserves_existing(tmp_path: Path) -> None:
    path = _seed_cfg(
        tmp_path,
        "storage:\n  root: .anvyc\n"
        "secrets:\n  entries:\n    - name: first\n      backend: op\n      ref: op://a/b/c\n",
    )
    register_entry(
        SecretEntry("second", BACKEND_SOPS, file="~/c.json", key="pw"), config_path=path
    )
    cfg = load_anvyc_config(path)
    assert [e.name for e in cfg.secrets.entries] == ["first", "second"]
    assert cfg.storage.root == ".anvyc"  # 기존 블록 보존


def test_register_entry_dup_name_raises(tmp_path: Path) -> None:
    path = _seed_cfg(
        tmp_path,
        "secrets:\n  entries:\n    - name: AWS\n      backend: op\n      ref: op://a/b/c\n",
    )
    with pytest.raises(SecretAddError):
        register_entry(SecretEntry("AWS", BACKEND_OP, ref="op://x/y/z"), config_path=path)


def test_register_entry_no_config_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # HOME + cwd 를 빈 tmp 로 격리 → 어떤 candidate path 도 존재하지 않음 → source None
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SecretAddError):
        register_entry(
            SecretEntry("k", BACKEND_OP, ref="op://a/b/c"), config_path=tmp_path / "nope.yaml"
        )


# ---- get_entry_by_name / resolve_command ----

def test_get_entry_by_name(tmp_path: Path) -> None:
    path = _seed_cfg(
        tmp_path,
        "secrets:\n  entries:\n    - name: AWS\n      backend: op\n      ref: op://a/b/c\n",
    )
    cfg = load_anvyc_config(path)
    found = get_entry_by_name(cfg, "AWS")
    assert found is not None
    assert found.backend == "op"
    assert get_entry_by_name(cfg, "nope") is None


def test_resolve_command_op() -> None:
    cmd = resolve_command(SecretEntry("x", BACKEND_OP, ref="op://a/b/c"))
    assert cmd == ["op", "read", "--no-newline", "op://a/b/c"]


def test_resolve_command_sops_binary() -> None:
    cmd = resolve_command(SecretEntry("x", BACKEND_SOPS, file="/tmp/c.sops.json"))
    assert cmd[:2] == ["sops", "-d"]
    assert "--extract" not in cmd


def test_resolve_command_sops_inplace_key() -> None:
    cmd = resolve_command(SecretEntry("x", BACKEND_SOPS, file="/tmp/c.json", key="pw"))
    assert "--extract" in cmd
    assert '["pw"]' in cmd


def test_resolve_command_unknown_backend() -> None:
    with pytest.raises(SecretGetError):
        resolve_command(SecretEntry("x", "hashicorp-vault"))
