"""core/aws_profile_state — 인증 방식 탐지 + profile 상태 판정."""
import json
from datetime import UTC, datetime
from pathlib import Path

from anvyc.core.aws_profile_state import (
    AUTH_ASSUME_ROLE,
    AUTH_CREDENTIAL_PROCESS,
    AUTH_INCOMPLETE,
    AUTH_SSO,
    AUTH_STATIC,
    AUTH_STATIC_TEMP,
    AUTH_UNDEFINED,
    AUTH_WEB_IDENTITY,
    TOKEN_NONE,
    detect_auth_method,
    evaluate_profile_state,
)


def test_detect_sso() -> None:
    assert detect_auth_method({"sso_session": "ws"}, has_static=False) == AUTH_SSO
    assert detect_auth_method({"sso_start_url": "u"}, has_static=False) == AUTH_SSO


def test_detect_assume_role() -> None:
    keys = {"role_arn": "arn:...", "source_profile": "base"}
    assert detect_auth_method(keys, has_static=False) == AUTH_ASSUME_ROLE


def test_detect_credential_process() -> None:
    assert detect_auth_method({"credential_process": "aws-vault exec x"}, has_static=False) == AUTH_CREDENTIAL_PROCESS


def test_detect_web_identity() -> None:
    assert detect_auth_method({"web_identity_token_file": "/t"}, has_static=False) == AUTH_WEB_IDENTITY


def test_detect_static_and_temp() -> None:
    assert detect_auth_method({}, has_static=True) == AUTH_STATIC
    assert detect_auth_method({"aws_session_token": "x"}, has_static=True) == AUTH_STATIC_TEMP


def test_detect_incomplete() -> None:
    assert detect_auth_method({"region": "us-east-1"}, has_static=False) == AUTH_INCOMPLETE


def test_detect_precedence_sso_over_static() -> None:
    # sso_session + 정적 키가 공존해도 SSO 우선.
    assert detect_auth_method({"sso_session": "ws"}, has_static=True) == AUTH_SSO


_NOW = datetime(2026, 6, 4, tzinfo=UTC)


def _home(tmp_path: Path, config: str = "", credentials: str = "") -> Path:
    aws = tmp_path / ".aws"
    aws.mkdir(parents=True)
    if config:
        (aws / "config").write_text(config, encoding="utf-8")
    if credentials:
        (aws / "credentials").write_text(credentials, encoding="utf-8")
    return tmp_path


def _write_sso_cache(home: Path, start_url: str, expires_at: str) -> None:
    cache = home / ".aws" / "sso" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "tok.json").write_text(
        json.dumps({"startUrl": start_url, "expiresAt": expires_at}), encoding="utf-8"
    )


def test_eval_undefined(tmp_path: Path) -> None:
    home = _home(tmp_path, "[profile other]\nregion = x\n")
    st = evaluate_profile_state("ghost", home=home, now=_NOW)
    assert st.defined is False
    assert st.auth_method == AUTH_UNDEFINED


def test_eval_sso_valid(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\n\n"
        "[profile dev]\nsso_session = ws\n",
    )
    _write_sso_cache(home, "https://u/start", "2026-06-05T00:00:00Z")  # +1d → valid
    st = evaluate_profile_state("dev", home=home, now=_NOW)
    assert st.auth_method == "sso"
    assert st.status == "valid"
    assert st.sso_session == "ws"


def test_eval_sso_expired(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\n\n[profile dev]\nsso_session = ws\n",
    )
    _write_sso_cache(home, "https://u/start", "2026-06-03T00:00:00Z")  # -1d → expired
    st = evaluate_profile_state("dev", home=home, now=_NOW)
    assert st.status == "expired"


def test_eval_sso_not_logged_in(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\n\n[profile dev]\nsso_session = ws\n",
    )
    # 캐시 디렉터리 없음 → 미로그인
    st = evaluate_profile_state("dev", home=home, now=_NOW)
    assert st.status == TOKEN_NONE


def test_eval_static(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[profile legacy]\nregion = us-east-1\n",
        credentials="[legacy]\naws_access_key_id = AKIA_X\n",
    )
    st = evaluate_profile_state("legacy", home=home, now=_NOW)
    assert st.auth_method == "static"
    assert st.status == "present"


def test_eval_assume_role_source_ok(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[profile base]\nregion = x\n\n[profile deploy]\nrole_arn = arn:aws:iam::1:role/r\nsource_profile = base\n",
    )
    st = evaluate_profile_state("deploy", home=home, now=_NOW)
    assert st.auth_method == "assume_role"
    assert st.status == "source_ok"
    assert st.source_profile == "base"


def test_eval_assume_role_source_missing(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[profile deploy]\nrole_arn = arn:aws:iam::1:role/r\nsource_profile = gone\n",
    )
    st = evaluate_profile_state("deploy", home=home, now=_NOW)
    assert st.status == "source_missing"


def test_eval_credential_process_missing(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[profile vault]\ncredential_process = /no/such/bin-xyz exec x\n",
    )
    st = evaluate_profile_state("vault", home=home, now=_NOW)
    assert st.auth_method == "credential_process"
    assert st.status == "cmd_missing"


def test_eval_web_identity(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[profile oidc]\nrole_arn = arn:aws:iam::1:role/r\nweb_identity_token_file = /no/token\n",
    )
    st = evaluate_profile_state("oidc", home=home, now=_NOW)
    assert st.auth_method == "web_identity"
    assert st.token_file_exists is False


def test_eval_incomplete(tmp_path: Path) -> None:
    home = _home(tmp_path, "[profile bare]\nregion = us-east-1\n")
    st = evaluate_profile_state("bare", home=home, now=_NOW)
    assert st.auth_method == "incomplete"
