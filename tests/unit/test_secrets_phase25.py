"""Unit tests for CP-15 Phase 2.5 — keychain / aws-vault backends (add/get)."""
from __future__ import annotations

import pytest

from anvyc.core.config import SecretEntry
from anvyc.core.secrets import (
    ADD_BACKENDS,
    BACKEND_AWS_VAULT,
    BACKEND_KEYCHAIN,
    BACKEND_OP,
    BACKEND_SOPS,
    SecretAddError,
    SecretGetError,
    _entry_to_dict,
    plan_add,
    resolve_command,
)


def test_add_backends_includes_all_four() -> None:
    assert set(ADD_BACKENDS) == {
        BACKEND_OP, BACKEND_SOPS, BACKEND_KEYCHAIN, BACKEND_AWS_VAULT
    }


# ---- keychain add ----

def test_plan_add_keychain() -> None:
    plan = plan_add("DB_PW", "keychain", service="anvyc", account="db")
    assert plan.entry.backend == BACKEND_KEYCHAIN
    assert plan.entry.service == "anvyc"
    assert plan.entry.account == "db"
    # -w 가 마지막 (security hidden 프롬프트) + -U (업데이트 허용)
    assert plan.command == [
        "security", "add-generic-password", "-U", "-s", "anvyc", "-a", "db", "-w"
    ]
    assert plan.command[-1] == "-w"


def test_plan_add_keychain_requires_service_and_account() -> None:
    with pytest.raises(SecretAddError):
        plan_add("DB_PW", "keychain", service="anvyc")  # account 누락
    with pytest.raises(SecretAddError):
        plan_add("DB_PW", "keychain", account="db")  # service 누락


# ---- aws-vault add ----

def test_plan_add_aws_vault() -> None:
    plan = plan_add("aws/prd", "aws-vault", profile="my-prd")
    assert plan.entry.backend == BACKEND_AWS_VAULT
    assert plan.entry.profile == "my-prd"
    assert plan.command == ["aws-vault", "add", "my-prd"]


def test_plan_add_aws_vault_requires_profile() -> None:
    with pytest.raises(SecretAddError):
        plan_add("aws/prd", "aws-vault")


# ---- _entry_to_dict for new backends ----

def test_entry_to_dict_keychain() -> None:
    d = _entry_to_dict(SecretEntry("DB", BACKEND_KEYCHAIN, service="anvyc", account="db"))
    assert d == {"name": "DB", "backend": "keychain", "service": "anvyc", "account": "db"}


def test_entry_to_dict_aws_vault() -> None:
    d = _entry_to_dict(SecretEntry("prd", BACKEND_AWS_VAULT, profile="my-prd"))
    assert d == {"name": "prd", "backend": "aws-vault", "profile": "my-prd"}


# ---- resolve_command for new backends ----

def test_resolve_command_keychain() -> None:
    cmd = resolve_command(SecretEntry("x", BACKEND_KEYCHAIN, service="anvyc", account="db"))
    assert cmd == [
        "security", "find-generic-password", "-w", "-s", "anvyc", "-a", "db"
    ]


def test_resolve_command_aws_vault_directs_to_exec() -> None:
    with pytest.raises(SecretGetError, match="exec"):
        resolve_command(SecretEntry("x", BACKEND_AWS_VAULT, profile="my-prd"))
