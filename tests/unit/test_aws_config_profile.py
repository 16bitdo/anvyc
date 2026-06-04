"""utils/aws_config — profile 섹션/credentials/sso meta 조회."""
from pathlib import Path

from anvyc.utils.aws_config import load_credentials_profile_names, load_profile_config


def test_profile_config_named(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text(
        "[profile ws-dev]\nregion = ap-northeast-2\nsso_session = ws\n", encoding="utf-8"
    )
    keys = load_profile_config("ws-dev", cfg)
    assert keys == {"region": "ap-northeast-2", "sso_session": "ws"}


def test_profile_config_default_section(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text("[default]\nregion = us-east-1\n", encoding="utf-8")
    assert load_profile_config("default", cfg) == {"region": "us-east-1"}


def test_profile_config_missing_profile(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text("[profile a]\nregion = x\n", encoding="utf-8")
    assert load_profile_config("nope", cfg) is None


def test_profile_config_missing_file(tmp_path: Path) -> None:
    assert load_profile_config("a", tmp_path / "none") is None


def test_credentials_names(tmp_path: Path) -> None:
    creds = tmp_path / "credentials"
    creds.write_text(
        "[default]\naws_access_key_id = AKIA_X\n\n[legacy]\naws_access_key_id = AKIA_Y\n",
        encoding="utf-8",
    )
    assert load_credentials_profile_names(creds) == {"default", "legacy"}


def test_credentials_missing_file(tmp_path: Path) -> None:
    assert load_credentials_profile_names(tmp_path / "none") == set()
