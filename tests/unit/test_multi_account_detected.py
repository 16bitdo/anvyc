"""multi-account-detected check 단위 테스트."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.multi_account_detected import MultiAccountDetectedCheck


def _write_aws_config(path: Path, profiles: list[str]) -> None:
    lines: list[str] = []
    for name in profiles:
        if name == "default":
            lines.append("[default]\nregion = ap-northeast-2\n")
        else:
            lines.append(f"[profile {name}]\nregion = ap-northeast-2\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


@pytest.fixture
def patched_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict:
    aws_cfg = tmp_path / "aws" / "config"
    ssh_cfg = tmp_path / "ssh" / "config"
    cursor_projects = tmp_path / "cursor" / "projects"

    monkeypatch.setattr(
        "anvyc.utils.aws_config.DEFAULT_AWS_CONFIG", aws_cfg
    )
    monkeypatch.setattr(
        "anvyc.checks.multi_account_detected.DEFAULT_SSH_CONFIG", ssh_cfg
    )
    monkeypatch.setattr(
        "anvyc.checks.multi_account_detected.DEFAULT_CURSOR_PROJECTS",
        cursor_projects,
    )
    return {
        "aws_cfg": aws_cfg,
        "ssh_cfg": ssh_cfg,
        "cursor_projects": cursor_projects,
    }


def test_aws_only_multi_yields_info(patched_sources: dict) -> None:
    """AWS profile ≥ 2 (default 제외) 단독 감지."""
    _write_aws_config(
        patched_sources["aws_cfg"],
        ["default", "ws-dev", "company-audit", "company-prd"],
    )
    res = MultiAccountDetectedCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "AWS profile" in res[0].message
    assert "ws-dev" in res[0].message


def test_aws_single_profile_skipped(patched_sources: dict) -> None:
    """default + 1 profile 만 있으면 multi-account 판정 안 함."""
    _write_aws_config(patched_sources["aws_cfg"], ["default", "ws-dev"])
    res = MultiAccountDetectedCheck().run(CheckContext())
    assert res == []


def test_github_ssh_alias_yields_info(patched_sources: dict) -> None:
    ssh_cfg = patched_sources["ssh_cfg"]
    ssh_cfg.parent.mkdir(parents=True, exist_ok=True)
    ssh_cfg.write_text(
        textwrap.dedent("""\
        Host github.com-16bitdo
            HostName github.com
            IdentityFile ~/.ssh/id_ed25519_16bitdo

        Host github.com-secondary
            HostName github.com
            IdentityFile ~/.ssh/id_ed25519_secondary
        """)
    )
    res = MultiAccountDetectedCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "GitHub SSH alias" in res[0].message
    assert "16bitdo" in res[0].message
    assert "secondary" in res[0].message


def test_cursor_alias_symlink_yields_info(patched_sources: dict) -> None:
    cursor_projects = patched_sources["cursor_projects"]
    cursor_projects.mkdir(parents=True, exist_ok=True)
    target = cursor_projects / "Users-edward-Documents"
    target.mkdir()
    alias = cursor_projects / "Users-aliasuser-Documents"
    os.symlink(target, alias)

    res = MultiAccountDetectedCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "Cursor user alias symlink" in res[0].message
    assert "Users-aliasuser-Documents" in res[0].message


def test_all_sources_absent_yields_zero(patched_sources: dict) -> None:
    """모든 source 미존재 → 0 결과."""
    res = MultiAccountDetectedCheck().run(CheckContext())
    assert res == []


def test_combined_aws_plus_ssh_yields_two(patched_sources: dict) -> None:
    """두 영역 동시 감지 시 결과 2건 (각각 1)."""
    _write_aws_config(
        patched_sources["aws_cfg"],
        ["default", "ws-dev", "company-audit"],
    )
    ssh_cfg = patched_sources["ssh_cfg"]
    ssh_cfg.parent.mkdir(parents=True, exist_ok=True)
    ssh_cfg.write_text("Host github.com-16bitdo\n  HostName github.com\n")

    res = MultiAccountDetectedCheck().run(CheckContext())
    assert len(res) == 2
    severities = {r.severity for r in res}
    assert severities == {Severity.INFO}
