"""detect_aws_sso 가 ~/.aws/config 로 profiles/sso_session 을 채우는지 (identifier 불변)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from anvyc.core.creds import detect_aws_sso

_NOW = datetime(2026, 5, 30, tzinfo=UTC)


def test_detect_aws_sso_fills_profiles(tmp_path: Path) -> None:
    cache = tmp_path / ".aws" / "sso" / "cache"
    cache.mkdir(parents=True)
    (cache / "x.json").write_text(
        json.dumps(
            {"startUrl": "https://d-x.awsapps.com/start", "expiresAt": "2099-01-01T00:00:00Z"}
        ),
        encoding="utf-8",
    )
    (tmp_path / ".aws" / "config").write_text(
        "[sso-session aiforge]\nsso_start_url = https://d-x.awsapps.com/start\n\n"
        "[profile dev]\nsso_session = aiforge\n\n[profile prd]\nsso_session = aiforge\n",
        encoding="utf-8",
    )
    creds = detect_aws_sso(tmp_path, warn_threshold_days=7, now=_NOW)
    assert len(creds) == 1
    c = creds[0]
    assert c.sso_session == "aiforge"
    assert c.profiles == ("dev", "prd")
    assert c.identifier == "https://d-x.awsapps.com/start"  # 불변 (anvyx #34 매칭 키)


def test_detect_aws_sso_no_config_empty_profiles(tmp_path: Path) -> None:
    """config 부재 → profiles=()/sso_session=None (기존 동작 유지, additive)."""
    cache = tmp_path / ".aws" / "sso" / "cache"
    cache.mkdir(parents=True)
    (cache / "x.json").write_text(
        json.dumps({"startUrl": "https://u/start", "expiresAt": "2099-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    creds = detect_aws_sso(tmp_path, warn_threshold_days=7, now=_NOW)
    assert creds[0].profiles == ()
    assert creds[0].sso_session is None
    assert creds[0].to_dict()["identifier"] == "https://u/start"  # JSON 직렬화에 identifier 유지
