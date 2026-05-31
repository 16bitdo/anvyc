"""creds_expiry._cred_label / _rotate_hint — aws_sso 식별 라벨(sso_session/profiles)."""

from anvyc.checks.creds_expiry import _cred_label, _rotate_hint
from anvyc.core.creds import CredentialStatus


def _sso(
    session: str | None, profiles: tuple[str, ...], identifier: str = "https://d-x/start"
) -> CredentialStatus:
    return CredentialStatus(
        kind="aws_sso",
        identifier=identifier,
        source="x",
        expires_at=None,
        expires_in_seconds=None,
        status="expired",
        profiles=profiles,
        sso_session=session,
    )


def test_label_uses_sso_session_and_profiles() -> None:
    label = _cred_label(_sso("aiforge", ("dev", "prd")))
    assert "aiforge" in label and "dev" in label and "prd" in label
    assert "d-x" not in label  # 불투명 startUrl 대신 session 이름


def test_label_truncates_many_profiles() -> None:
    label = _cred_label(_sso("aiforge", ("a", "b", "c", "d", "e")))
    assert "+2" in label  # 처음 3 표시 + 2 더


def test_label_fallback_to_starturl_when_no_session() -> None:
    assert "https://leg/start" in _cred_label(_sso(None, (), identifier="https://leg/start"))


def test_label_non_aws_uses_identifier() -> None:
    c = CredentialStatus(
        kind="github",
        identifier="github.com/u",
        source="x",
        expires_at=None,
        expires_in_seconds=None,
        status="expired",
    )
    assert "github.com/u" in _cred_label(c)


def test_rotate_hint_names_sso_session() -> None:
    assert "--sso-session aiforge" in _rotate_hint(_sso("aiforge", ("dev",)))
