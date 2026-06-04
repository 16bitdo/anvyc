"""unused-aws-profiles check 단위 테스트 (v0.7.0)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.unused_aws_profiles import UnusedAwsProfilesCheck


def _write_aws_config(path: Path, profiles: list[str]) -> None:
    lines: list[str] = []
    for name in profiles:
        if name == "default":
            lines.append("[default]\nregion = ap-northeast-2\n")
        else:
            lines.append(f"[profile {name}]\nregion = ap-northeast-2\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def _write_envrc(project: Path, profile: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / ".envrc").write_text(f"export AWS_PROFILE={profile}\n")


@pytest.fixture
def patched_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    docs = tmp_path / "Documents"
    docs.mkdir()
    aws_cfg = tmp_path / "aws" / "config"
    monkeypatch.setattr(
        "anvyc.core.project_roots.resolve_project_roots",
        lambda config=None: (str(docs),),
    )
    monkeypatch.setattr(
        "anvyc.core.project_roots.resolve_projects",
        lambda config=None: (),
    )
    monkeypatch.setattr(
        "anvyc.core.project_roots.resolve_excludes",
        lambda config=None: (),
    )
    monkeypatch.setattr(
        "anvyc.utils.aws_config.DEFAULT_AWS_CONFIG", aws_cfg
    )
    return {"docs": docs, "aws_cfg": aws_cfg}


def test_unused_profiles_yields_info(patched_paths: dict[str, Any]) -> None:
    """defined 3 profile + .envrc 가 1개만 사용 → 2 unused."""
    _write_aws_config(
        patched_paths["aws_cfg"],
        ["default", "ws-dev", "ws-audit", "ws-prd"],
    )
    _write_envrc(patched_paths["docs"] / "proj-a", "ws-dev")

    res = UnusedAwsProfilesCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "2" in res[0].message  # 2 unused
    assert "ws-audit" in res[0].message
    assert "ws-prd" in res[0].message


def test_all_profiles_used_yields_zero(patched_paths: dict[str, Any]) -> None:
    """defined 모두 사용 중 → 0 결과."""
    _write_aws_config(patched_paths["aws_cfg"], ["default", "ws-dev"])
    _write_envrc(patched_paths["docs"] / "proj-a", "ws-dev")

    res = UnusedAwsProfilesCheck().run(CheckContext())
    assert res == []


def test_no_aws_config_yields_zero(patched_paths: dict[str, Any]) -> None:
    """`~/.aws/config` 부재 → silent skip."""
    res = UnusedAwsProfilesCheck().run(CheckContext())
    assert res == []


def test_only_default_profile_yields_zero(patched_paths: dict[str, Any]) -> None:
    """[default] 만 정의돼 있음 → unused 판정 안 함 (default 는 fallback 으로 제외)."""
    _write_aws_config(patched_paths["aws_cfg"], ["default"])
    res = UnusedAwsProfilesCheck().run(CheckContext())
    assert res == []


def test_no_envrcs_all_profiles_unused(patched_paths: dict[str, Any]) -> None:
    """.envrc 가 0 건이고 profile 이 정의돼 있음 → 모두 unused INFO."""
    _write_aws_config(patched_paths["aws_cfg"], ["default", "ws-dev", "ws-prd"])
    res = UnusedAwsProfilesCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "ws-dev" in res[0].message
    assert "ws-prd" in res[0].message


def test_unused_honors_individual_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """컨테이너는 비우고, 개별 project 의 .envrc 가 profile 을 '사용 중'으로 만든다."""
    aws_cfg = tmp_path / "aws_config"
    aws_cfg.write_text("[profile used-prof]\n[profile lonely]\n")
    monkeypatch.setattr("anvyc.utils.aws_config.DEFAULT_AWS_CONFIG", aws_cfg)
    empty = tmp_path / "empty"
    empty.mkdir()
    indiv = tmp_path / "proj"
    indiv.mkdir()
    (indiv / ".envrc").write_text("export AWS_PROFILE=used-prof\n")
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(empty),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    results = UnusedAwsProfilesCheck().run(CheckContext())
    msg = " ".join(r.message for r in results)
    assert "lonely" in msg and "used-prof" not in msg  # used-prof 는 개별 project 가 사용
