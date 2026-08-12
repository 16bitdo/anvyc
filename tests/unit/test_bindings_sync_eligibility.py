"""바인딩의 rule 27 sync 적격성 — 자격 본문을 담을 수 없어야 한다."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core import account_manifest

_FORBIDDEN = {"token", "secret", "password", "oauth_token", "private_key", "credential"}


def test_binding_schema_has_no_credential_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = tmp_path / "binds"
    b.mkdir()
    (b / "bindings.test-machine.yaml").write_text(
        "version: 1\nmachine: test-machine\naccounts:\n"
        "  a:\n    github_login: x\n    gh_config_dir: ~/.config/gh-x\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANVYC_ACCOUNT_BINDINGS_DIR", str(b))
    monkeypatch.setattr(account_manifest, "machine_name", lambda: "test-machine")
    for binding in account_manifest.load_bindings().values():
        assert not (set(k.lower() for k in binding) & _FORBIDDEN)


def test_resolved_account_exposes_no_credentials() -> None:
    """ResolvedAccount 는 자격 본문 필드를 갖지 않는다 (구조적 불변식)."""
    fields = set(account_manifest.ResolvedAccount.__dataclass_fields__)
    assert not (fields & _FORBIDDEN)
    assert fields == {
        "ownership_id", "github_login", "commit_email",
        "ssh_alias", "gh_config_dir", "claude_config_dir",
    }


def test_bindings_filename_is_machine_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    """파일명이 머신별이라 rule 27 §2 충돌이 구조적으로 발생하지 않는다."""
    monkeypatch.setattr(account_manifest, "machine_name", lambda: "machine-a")
    a = account_manifest.bindings_path().name
    monkeypatch.setattr(account_manifest, "machine_name", lambda: "machine-b")
    b = account_manifest.bindings_path().name
    assert a != b and a.startswith("bindings.") and b.startswith("bindings.")
