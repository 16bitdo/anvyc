"""core/aws_config_edit — profile CRUD (surgical 텍스트 편집)."""
from pathlib import Path

import pytest

from anvyc.core.aws_config_edit import (
    AwsConfigEditError,
    create_profile,
    edit_profile,
    remove_profile,
)


def _cfg(tmp_path: Path, text: str = "") -> Path:
    p = tmp_path / "config"
    if text:
        p.write_text(text, encoding="utf-8")
    return p


def test_create_into_empty_file(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    res = create_profile(
        cfg, "ws-dev", sso_session="ws", start_url="https://u/start",
        sso_region="ap-northeast-2", account_id="111122223333",
        role_name="Dev", region="ap-northeast-2", output="json",
    )
    assert res.written is True and res.changed is True
    text = cfg.read_text(encoding="utf-8")
    assert "[sso-session ws]" in text
    assert "sso_start_url = https://u/start" in text
    assert "[profile ws-dev]" in text
    assert "sso_session = ws" in text
    assert "sso_account_id = 111122223333" in text
    # 결과가 유효 INI 인지 (round-trip)
    from anvyc.utils.aws_config import load_profile_config
    keys = load_profile_config("ws-dev", cfg)
    assert keys is not None and keys["sso_role_name"] == "Dev"


def test_create_appends_preserving_existing_and_comments(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "# top comment\n[profile keep]\nregion = us-east-1\n")
    res = create_profile(cfg, "new", region="us-west-2")
    text = cfg.read_text(encoding="utf-8")
    assert "# top comment" in text  # 주석 보존
    assert "[profile keep]" in text  # 기존 보존
    assert "[profile new]" in text
    assert res.backup_path is not None and res.backup_path.is_file()  # .bak


def test_create_existing_sso_session_is_referenced_not_duplicated(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\nsso_region = ap-northeast-2\n",
    )
    create_profile(cfg, "second", sso_session="ws", account_id="9", role_name="R")
    text = cfg.read_text(encoding="utf-8")
    assert text.count("[sso-session ws]") == 1  # 중복 생성 안 함
    assert "[profile second]" in text
    assert "sso_session = ws" in text


def test_create_existing_profile_errors(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile dup]\nregion = x\n")
    with pytest.raises(AwsConfigEditError, match="이미 존재"):
        create_profile(cfg, "dup", region="y")


def test_create_new_sso_session_requires_start_url(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    with pytest.raises(AwsConfigEditError, match="start-url"):
        create_profile(cfg, "p", sso_session="brand-new", account_id="9")


def test_create_dry_run_writes_nothing(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile a]\nregion = x\n")
    before = cfg.read_text(encoding="utf-8")
    res = create_profile(cfg, "b", region="y", write=False)
    assert res.written is False
    assert res.changed is True and res.diff  # diff 는 계산됨
    assert cfg.read_text(encoding="utf-8") == before  # 파일 불변


def test_create_rollback_on_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # _validate_ini 가 실패하면 원본 복구 + 에러 (방어 분기).
    import anvyc.core.aws_config_edit as ace

    cfg = _cfg(tmp_path, "[profile a]\nregion = x\n")
    before = cfg.read_text(encoding="utf-8")

    def boom(_text: str) -> None:
        raise AwsConfigEditError("forced invalid")

    monkeypatch.setattr(ace, "_validate_ini", boom)
    with pytest.raises(AwsConfigEditError):
        create_profile(cfg, "b", region="y")
    assert cfg.read_text(encoding="utf-8") == before  # 롤백됨


def test_edit_replaces_key_in_place_preserving_comments(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "[profile dev]\n# keep me\nregion = us-east-1\noutput = json\n\n[profile other]\nregion = z\n",
    )
    res = edit_profile(cfg, "dev", sets={"region": "ap-northeast-2"})
    text = cfg.read_text(encoding="utf-8")
    assert "region = ap-northeast-2" in text
    assert "region = us-east-1" not in text
    assert "# keep me" in text                 # 섹션 내 주석 보존
    assert "[profile other]\nregion = z" in text  # 다른 섹션 불변
    assert res.changed is True


def test_edit_inserts_new_key(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile dev]\nregion = us-east-1\n")
    edit_profile(cfg, "dev", sets={"output": "yaml"})
    from anvyc.utils.aws_config import load_profile_config
    keys = load_profile_config("dev", cfg)
    assert keys is not None and keys["output"] == "yaml" and keys["region"] == "us-east-1"


def test_edit_rejects_static_cred_keys(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile dev]\nregion = us-east-1\n")
    with pytest.raises(AwsConfigEditError, match="정적 자격 키"):
        edit_profile(cfg, "dev", sets={"aws_access_key_id": "AKIA_X"})


def test_edit_missing_profile_errors(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile dev]\nregion = x\n")
    with pytest.raises(AwsConfigEditError, match="없습니다"):
        edit_profile(cfg, "ghost", sets={"region": "y"})


def test_remove_deletes_section_preserving_rest(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "# header\n[profile keep]\nregion = a\n\n[profile gone]\nregion = b\n\n[profile keep2]\nregion = c\n",
    )
    res = remove_profile(cfg, "gone")
    text = cfg.read_text(encoding="utf-8")
    assert "[profile gone]" not in text
    assert "# header" in text
    assert "[profile keep]" in text and "[profile keep2]" in text
    assert res.changed is True and res.backup_path is not None


def test_remove_warns_orphan_sso_session(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\n\n[profile only]\nsso_session = ws\n",
    )
    res = remove_profile(cfg, "only")
    assert any("orphan" in w for w in res.warnings)
    # 자동 삭제 안 함
    assert "[sso-session ws]" in cfg.read_text(encoding="utf-8")


def test_remove_no_orphan_warning_when_session_still_used(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\n\n"
        "[profile a]\nsso_session = ws\n\n[profile b]\nsso_session = ws\n",
    )
    res = remove_profile(cfg, "a")
    assert not any("orphan" in w for w in res.warnings)


def test_remove_missing_profile_errors(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile a]\nregion = x\n")
    with pytest.raises(AwsConfigEditError, match="없습니다"):
        remove_profile(cfg, "ghost")


def test_remove_profile_with_internal_blank_body(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "[profile keep]\nregion = a\n\n"
        "[profile gone]\nregion = b\n\noutput = json\n\n"
        "[profile keep2]\nregion = c\n",
    )
    res = remove_profile(cfg, "gone")
    text = cfg.read_text(encoding="utf-8")
    assert res.written is True
    assert "[profile gone]" not in text
    assert "output = json" not in text   # 본문 내부 빈 줄 뒤 키도 함께 제거
    assert "[profile keep]" in text and "[profile keep2]" in text
    from anvyc.utils.aws_config import load_aws_profile_names
    assert load_aws_profile_names(cfg) == {"keep", "keep2"}


def test_remove_absorbs_own_comment_preserves_next(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "# Dev account\n[profile dev]\nregion = us-east-1\n\n"
        "# Prod account - DANGER\n[profile prod]\nregion = us-west-2\n\n"
        "# Staging account\n[profile stg]\nregion = eu-west-1\n",
    )
    remove_profile(cfg, "prod")
    text = cfg.read_text(encoding="utf-8")
    assert "[profile prod]" not in text
    assert "# Prod account - DANGER" not in text     # 제거 대상의 주석도 함께 삭제
    assert "# Staging account" in text               # 다음 섹션 주석 보존
    assert "# Dev account" in text and "[profile dev]" in text and "[profile stg]" in text
    assert "# Staging account\n[profile stg]" in text  # 오귀속 없음(주석이 stg 바로 위 유지)
