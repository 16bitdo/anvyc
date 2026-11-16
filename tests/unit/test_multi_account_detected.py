"""multi-account-detected check 단위 테스트."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path
from typing import Any

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.multi_account_detected import (
    MultiAccountDetectedCheck,
    _read_github_ssh_aliases,
)


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
) -> dict[str, Any]:
    aws_cfg = tmp_path / "aws" / "config"
    ssh_cfg = tmp_path / "ssh" / "config"
    cursor_projects = tmp_path / "cursor" / "projects"
    claude_home = tmp_path / "home"
    claude_home.mkdir()

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
    monkeypatch.setattr(
        "anvyc.checks.multi_account_detected.DEFAULT_CLAUDE_HOME", claude_home
    )
    return {
        "aws_cfg": aws_cfg,
        "ssh_cfg": ssh_cfg,
        "cursor_projects": cursor_projects,
        "claude_home": claude_home,
    }


def test_aws_only_multi_yields_info(patched_sources: dict[str, Any]) -> None:
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


def test_aws_single_profile_skipped(patched_sources: dict[str, Any]) -> None:
    """default + 1 profile 만 있으면 multi-account 판정 안 함."""
    _write_aws_config(patched_sources["aws_cfg"], ["default", "ws-dev"])
    res = MultiAccountDetectedCheck().run(CheckContext())
    assert res == []


def test_github_ssh_alias_yields_info(patched_sources: dict[str, Any]) -> None:
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


def test_cursor_alias_symlink_yields_info(patched_sources: dict[str, Any]) -> None:
    """Cursor user-alias symlink 감지 — root 세그먼트 무관 (dev 등)."""
    cursor_projects = patched_sources["cursor_projects"]
    cursor_projects.mkdir(parents=True, exist_ok=True)
    target = cursor_projects / "Users-edward-dev"
    target.mkdir()
    alias = cursor_projects / "Users-aliasuser-dev"
    os.symlink(target, alias)

    res = MultiAccountDetectedCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "Cursor user alias symlink" in res[0].message
    assert "Users-aliasuser-dev" in res[0].message


def test_claude_config_dirs_yield_info(patched_sources: dict[str, Any]) -> None:
    """`~/.claude-<account>` 디렉터리 감지 → INFO."""
    home: Path = patched_sources["claude_home"]
    (home / ".claude-edward").mkdir()
    (home / ".claude-jklee").mkdir()
    (home / ".claude").mkdir()  # 기본 디렉터리는 suffix 없음 — 무시 대상

    res = MultiAccountDetectedCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "Claude Code" in res[0].message
    assert ".claude-edward" in res[0].message
    assert ".claude-jklee" in res[0].message
    # suffix 없는 기본 `.claude` 는 glob `.claude-*` 에 안 걸려 제외 — 2건만 보고
    assert res[0].message.count(".claude-") == 2


def test_all_sources_absent_yields_zero(patched_sources: dict[str, Any]) -> None:
    """모든 source 미존재 → 0 결과."""
    res = MultiAccountDetectedCheck().run(CheckContext())
    assert res == []


def test_combined_aws_plus_ssh_yields_two(patched_sources: dict[str, Any]) -> None:
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


# ---------------------------------------------------------------------------
# `Host` 줄 파싱 — ssh_config(5): 한 줄에 패턴 여러 개, 키워드와 인자 사이 공백 또는 `=`
# ---------------------------------------------------------------------------

def _aliases(tmp_path: Path, body: str) -> list[str]:
    cfg = tmp_path / "ssh_config"
    cfg.write_text(textwrap.dedent(body))
    return _read_github_ssh_aliases(cfg)


def test_multiple_aliases_on_one_host_line(tmp_path: Path) -> None:
    """`Host` 한 줄의 별칭을 모두 감지한다 — 인자가 토큰 하나인 줄만 매치하던 정규식은 줄 전체를 놓쳤다."""
    assert _aliases(tmp_path, """\
        Host github.com-a github.com-b
            HostName github.com
        """) == ["github.com-a", "github.com-b"]


def test_alias_after_non_alias_pattern(tmp_path: Path) -> None:
    """첫 패턴이 별칭이 아니어도(`github.com`) 뒤의 별칭을 감지한다."""
    assert _aliases(tmp_path, """\
        Host github.com github.com-e
            HostName github.com
        """) == ["github.com-e"]


def test_equals_separator(tmp_path: Path) -> None:
    """ssh_config(5) 는 키워드와 인자 사이에 `=`(앞뒤 공백 선택)도 허용한다."""
    assert _aliases(tmp_path, """\
        Host=github.com-d
        Host = github.com-f
        """) == ["github.com-d", "github.com-f"]


def test_negated_pattern_is_not_an_alias(tmp_path: Path) -> None:
    """`!` 로 부정한 패턴은 그 호스트를 제외한다는 뜻 — 감지한 별칭이 아니다."""
    assert _aliases(tmp_path, """\
        Host github.com-a !github.com-old
        """) == ["github.com-a"]


def test_hostname_keyword_is_not_host(tmp_path: Path) -> None:
    """`HostName` 은 `Host` 가 아니다 — 키워드 접두사만 보는 매치로 섞이지 않게 지킨다."""
    assert _aliases(tmp_path, """\
        Host github.com-a
            HostName github.com-zzz
        """) == ["github.com-a"]


def test_wildcard_pattern_is_not_listed_as_alias(tmp_path: Path) -> None:
    """`github.com-*`·`github.com-?x` 는 여러 별칭에 설정을 거는 패턴이지 별칭이 아니다 — 목록에 올리지 않는다."""
    assert _aliases(tmp_path, """\
        Host github.com-*
            IdentitiesOnly yes
        Host github.com-a github.com-?x
        """) == ["github.com-a"]


def test_trailing_comment_is_not_patterns(tmp_path: Path) -> None:
    """`#` 로 시작하는 토큰부터는 주석이다 — OpenSSH 10.3 실측: 주석 속 별칭은 그 블록에 걸리지 않는다."""
    assert _aliases(tmp_path, """\
        Host github.com-a # 예전 github.com-old
        """) == ["github.com-a"]


def test_quoted_pattern_is_unquoted(tmp_path: Path) -> None:
    """ssh_config 인자는 큰따옴표로 감쌀 수 있다 — OpenSSH 는 벗겨서 매치한다."""
    assert _aliases(tmp_path, """\
        Host "github.com-q"
        """) == ["github.com-q"]
