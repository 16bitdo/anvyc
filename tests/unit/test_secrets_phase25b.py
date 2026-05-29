"""Unit tests for CP-15 Phase 2.5b — inject-wire (JIT 주입 라인 생성/추가)."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core.config import SecretEntry
from anvyc.core.secrets import (
    BACKEND_AWS_VAULT,
    BACKEND_KEYCHAIN,
    BACKEND_OP,
    BACKEND_SOPS,
    SecretInjectError,
    append_inject_line,
    plan_inject,
)

# ---- plan_inject ----

def test_plan_inject_op_export_line() -> None:
    plan = plan_inject(SecretEntry("AWS_KEY", BACKEND_OP, ref="op://a/b/c"), target="~/.envrc")
    assert plan.env_var == "AWS_KEY"
    assert plan.line == 'export AWS_KEY="$(op read --no-newline op://a/b/c)"'


def test_plan_inject_sops_inplace_key_quoted() -> None:
    plan = plan_inject(
        SecretEntry("DB_PW", BACKEND_SOPS, file="/tmp/c.json", key="pw"), target="/t/.envrc"
    )
    # shlex.join 이 ["pw"] 를 안전하게 quote
    assert plan.line == 'export DB_PW="$(sops -d --extract \'["pw"]\' /tmp/c.json)"'


def test_plan_inject_keychain() -> None:
    plan = plan_inject(
        SecretEntry("DB_PW", BACKEND_KEYCHAIN, service="anvyc", account="db"), target="/t/.envrc"
    )
    assert plan.line == 'export DB_PW="$(security find-generic-password -w -s anvyc -a db)"'


def test_plan_inject_env_var_override() -> None:
    # name 에 '/' → 자동 env var 불가, --env-var 로 명시
    plan = plan_inject(
        SecretEntry("pulumi/passphrase", BACKEND_OP, ref="op://a/b/c"),
        target="/t/.envrc",
        env_var="PULUMI_PASSPHRASE",
    )
    assert plan.env_var == "PULUMI_PASSPHRASE"
    assert plan.line.startswith('export PULUMI_PASSPHRASE="$(')


def test_plan_inject_invalid_env_var_raises() -> None:
    with pytest.raises(SecretInjectError):
        plan_inject(SecretEntry("pulumi/passphrase", BACKEND_OP, ref="op://a/b/c"), target="/t/.envrc")


def test_plan_inject_aws_vault_comment_guidance() -> None:
    plan = plan_inject(
        SecretEntry("aws/prd", BACKEND_AWS_VAULT, profile="my-prd"), target="/t/.envrc"
    )
    assert plan.env_var is None
    assert plan.line.startswith("# ")
    assert "aws-vault exec my-prd" in plan.line


# ---- append_inject_line ----

def test_append_inject_line_creates_and_appends(tmp_path: Path) -> None:
    target = tmp_path / ".envrc"
    target.write_text("export EXISTING=1\n", encoding="utf-8")
    line = 'export AWS_KEY="$(op read --no-newline op://a/b/c)"'
    written = append_inject_line(str(target), line)
    assert written == target
    text = target.read_text(encoding="utf-8")
    assert "export EXISTING=1" in text
    assert line in text
    # 쓰기 전 .bak 생성
    assert len(list(tmp_path.glob(".envrc.bak-*"))) == 1


def test_append_inject_line_creates_missing_file(tmp_path: Path) -> None:
    target = tmp_path / "sub" / ".envrc"
    line = 'export X="$(op read --no-newline op://a/b/c)"'
    append_inject_line(str(target), line)
    assert target.is_file()
    assert line in target.read_text(encoding="utf-8")


def test_append_inject_line_dup_raises(tmp_path: Path) -> None:
    target = tmp_path / ".envrc"
    line = 'export X="$(op read --no-newline op://a/b/c)"'
    target.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(SecretInjectError):
        append_inject_line(str(target), line)


def test_append_inject_line_no_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / ".envrc"
    target.write_text("export A=1", encoding="utf-8")  # 마지막 개행 없음
    line = 'export B="$(op read --no-newline op://a/b/c)"'
    append_inject_line(str(target), line)
    text = target.read_text(encoding="utf-8")
    assert "export A=1\nexport B=" in text  # 개행 보정
