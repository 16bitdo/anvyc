"""project-aws-profile-mapping check 단위 테스트.

monkeypatch 로 `DEFAULT_PROJECT_ROOT` 와 `DEFAULT_AWS_CONFIG` 를 격리하여
실제 사용자 환경 의존성 제거.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.project_aws_profile import ProjectAwsProfileMappingCheck


def _write_aws_config(path: Path, profiles: list[str]) -> None:
    """`~/.aws/config` 합성. 'default' 가 포함되면 [default] section 추가."""
    lines: list[str] = []
    for name in profiles:
        if name == "default":
            lines.append("[default]\nregion = ap-northeast-2\n")
        else:
            lines.append(f"[profile {name}]\nregion = ap-northeast-2\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def _write_envrc(project: Path, profile: str) -> Path:
    project.mkdir(parents=True, exist_ok=True)
    e = project / ".envrc"
    e.write_text(f'export AWS_PROFILE={profile}\n')
    return e


@pytest.fixture
def patched_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    docs = tmp_path / "Documents"
    docs.mkdir()
    aws_cfg = tmp_path / "aws" / "config"
    monkeypatch.setattr(
        "anvyc.checks.project_aws_profile.DEFAULT_PROJECT_ROOT", docs
    )
    monkeypatch.setattr(
        "anvyc.utils.aws_config.DEFAULT_AWS_CONFIG", aws_cfg
    )
    return {"docs": docs, "aws_cfg": aws_cfg}


def test_all_defined_yields_single_info(patched_paths: dict) -> None:
    """모든 .envrc 의 profile 이 aws/config 에 정의돼 있으면 INFO summary 1건."""
    docs = patched_paths["docs"]
    _write_envrc(docs / "proj-a", "ws-dev")
    _write_envrc(docs / "proj-b", "company-audit")
    _write_aws_config(patched_paths["aws_cfg"], ["default", "ws-dev", "company-audit"])

    res = ProjectAwsProfileMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "2개" in res[0].message
    assert "모두 정의" in res[0].message


def test_one_missing_yields_warning(patched_paths: dict) -> None:
    """일부 누락 시 누락마다 WARNING — summary INFO 발행 안 함."""
    docs = patched_paths["docs"]
    _write_envrc(docs / "proj-a", "ws-dev")
    _write_envrc(docs / "proj-b", "company-ghost")
    _write_aws_config(patched_paths["aws_cfg"], ["default", "ws-dev"])

    res = ProjectAwsProfileMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "company-ghost" in res[0].message
    assert res[0].location is not None
    assert res[0].location.name == ".envrc"
    assert res[0].suggestion is not None
    assert "aws configure" in res[0].suggestion


def test_no_envrcs_yields_silent(patched_paths: dict) -> None:
    """`.envrc` 부재 → 결과 0건 (silent)."""
    _write_aws_config(patched_paths["aws_cfg"], ["default", "ws-dev"])
    res = ProjectAwsProfileMappingCheck().run(CheckContext())
    assert res == []


def test_aws_config_absent_yields_all_missing(patched_paths: dict) -> None:
    """`~/.aws/config` 부재 → 모든 .envrc 의 profile 이 missing 처리."""
    docs = patched_paths["docs"]
    _write_envrc(docs / "proj-a", "ws-dev")
    # aws_cfg 자체를 쓰지 않음

    res = ProjectAwsProfileMappingCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "ws-dev" in res[0].message


def test_envrc_with_quoted_value(patched_paths: dict) -> None:
    """`export AWS_PROFILE="X"` 큰따옴표 형식도 파싱 OK."""
    docs = patched_paths["docs"]
    proj = docs / "proj-q"
    proj.mkdir()
    (proj / ".envrc").write_text(
        textwrap.dedent("""\
        # comment
        export AWS_PROFILE="ws-mgmt"  # inline comment
        """)
    )
    _write_aws_config(patched_paths["aws_cfg"], ["default", "ws-mgmt"])

    res = ProjectAwsProfileMappingCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
