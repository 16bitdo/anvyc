"""aws-profile-status check 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.checks.aws_profile_status import AwsProfileStatusCheck
from anvyc.checks.base import CheckContext, Severity


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
def patched_aws_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    cfg = tmp_path / "aws" / "config"
    monkeypatch.setattr("anvyc.utils.aws_config.DEFAULT_AWS_CONFIG", cfg)
    return cfg


def test_unset_yields_info_with_direnv_hint(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    _write_aws_config(patched_aws_config, ["default", "ws-dev"])

    res = AwsProfileStatusCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "미설정" in res[0].message
    assert "direnv" in (res[0].suggestion or "")


def test_set_and_defined_yields_info(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_PROFILE", "ws-dev")
    _write_aws_config(patched_aws_config, ["default", "ws-dev"])

    res = AwsProfileStatusCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "AWS_PROFILE=ws-dev" in res[0].message
    assert "정의됨" in res[0].message


def test_set_but_undefined_yields_warning(
    patched_aws_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_PROFILE", "ghost")
    _write_aws_config(patched_aws_config, ["default", "ws-dev"])

    res = AwsProfileStatusCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "ghost" in res[0].message
    assert "정의 안 됨" in res[0].message
    assert "aws configure --profile ghost" in (res[0].suggestion or "")
