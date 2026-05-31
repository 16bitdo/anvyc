"""utils/aws_config.load_aws_sso_index — startUrl → (sso_session, [profiles]) 역매핑."""

from pathlib import Path

from anvyc.utils.aws_config import load_aws_sso_index


def test_sso_index_modern_shared_session(tmp_path: Path) -> None:
    """신형: 여러 profile 이 한 sso-session 공유 → startUrl 1개에 profiles N."""
    cfg = tmp_path / "config"
    cfg.write_text(
        "[sso-session aiforge]\nsso_start_url = https://d-x.awsapps.com/start\n\n"
        "[profile dev]\nsso_session = aiforge\n\n"
        "[profile prd]\nsso_session = aiforge\n",
        encoding="utf-8",
    )
    idx = load_aws_sso_index(cfg)
    assert idx["https://d-x.awsapps.com/start"] == ("aiforge", ["dev", "prd"])


def test_sso_index_legacy_direct(tmp_path: Path) -> None:
    """구형: profile 에 sso_start_url 직접 (session 없음)."""
    cfg = tmp_path / "config"
    cfg.write_text(
        "[profile old]\nsso_start_url = https://leg.awsapps.com/start\n", encoding="utf-8"
    )
    idx = load_aws_sso_index(cfg)
    assert idx["https://leg.awsapps.com/start"] == (None, ["old"])


def test_sso_index_default_profile(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text(
        "[sso-session s]\nsso_start_url = https://u/start\n\n[default]\nsso_session = s\n",
        encoding="utf-8",
    )
    idx = load_aws_sso_index(cfg)
    assert idx["https://u/start"] == ("s", ["default"])


def test_sso_index_non_sso_profile_ignored(tmp_path: Path) -> None:
    """SSO 아닌 profile(region 만) → 인덱스에 없음."""
    cfg = tmp_path / "config"
    cfg.write_text("[profile plain]\nregion = ap-northeast-2\n", encoding="utf-8")
    assert load_aws_sso_index(cfg) == {}


def test_sso_index_missing_file(tmp_path: Path) -> None:
    assert load_aws_sso_index(tmp_path / "none") == {}
