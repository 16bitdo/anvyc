"""Unit tests for anvyc.core.creds (CP-5 1/3)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anvyc.core.creds import (
    AWS_SSO_WARN_DAYS,
    DEFAULT_KIND_WARN_DAYS,
    DEFAULT_WARN_THRESHOLD_DAYS,
    KIND_AWS_SSO,
    KIND_CLAUDE_OAUTH,
    KIND_GITHUB,
    SCHEMA_VERSION,
    STATUS_EXPIRED,
    STATUS_EXPIRING,
    STATUS_UNKNOWN,
    STATUS_VALID,
    collect_credentials,
    detect_aws_sso,
    detect_claude_oauth,
    detect_github,
)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def now_fixed() -> datetime:
    return datetime(2026, 5, 25, 0, 0, 0, tzinfo=UTC)


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def _write_sso(home: Path, name: str, expires_at: str | None, start_url: str = "https://x.awsapps.com/start") -> None:
    cache = home / ".aws" / "sso" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"startUrl": start_url, "clientId": "x", "clientSecret": "y"}
    if expires_at is not None:
        payload["expiresAt"] = expires_at
    (cache / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_detect_aws_sso_valid(fake_home: Path, now_fixed: datetime) -> None:
    _write_sso(fake_home, "a", _iso(now_fixed + timedelta(days=30)))
    out = detect_aws_sso(fake_home, warn_threshold_days=7, now=now_fixed)
    assert len(out) == 1
    assert out[0].kind == KIND_AWS_SSO
    assert out[0].status == STATUS_VALID
    assert out[0].expires_in_seconds is not None
    assert out[0].expires_in_seconds > 7 * 86400


def test_detect_aws_sso_expiring(fake_home: Path, now_fixed: datetime) -> None:
    _write_sso(fake_home, "a", _iso(now_fixed + timedelta(days=3)))
    out = detect_aws_sso(fake_home, warn_threshold_days=7, now=now_fixed)
    assert out[0].status == STATUS_EXPIRING


def test_detect_aws_sso_short_threshold_narrows_expiring(fake_home: Path, now_fixed: datetime) -> None:
    """per-kind 임계(aws_sso 1h): 6h 뒤 만료는 7d 면 expiring, 1h 면 valid (SSO 영구 노이즈 회피)."""
    _write_sso(fake_home, "a", _iso(now_fixed + timedelta(hours=6)))
    assert detect_aws_sso(fake_home, warn_threshold_days=7, now=now_fixed)[0].status == STATUS_EXPIRING
    assert (
        detect_aws_sso(fake_home, warn_threshold_days=AWS_SSO_WARN_DAYS, now=now_fixed)[0].status
        == STATUS_VALID
    )


def test_collect_credentials_kind_warn_days_override(fake_home: Path, now_fixed: datetime) -> None:
    """collect_credentials(kind_warn_days) 가 aws_sso 만 좁힌다 (전역 7d 유지)."""
    _write_sso(fake_home, "a", _iso(now_fixed + timedelta(hours=6)))
    base = collect_credentials(
        home=fake_home, warn_threshold_days=7, probe_github_expiry=False, now=now_fixed
    )
    sso = [c for c in base.credentials if c.kind == KIND_AWS_SSO]
    assert sso and sso[0].status == STATUS_EXPIRING
    narrowed = collect_credentials(
        home=fake_home,
        warn_threshold_days=7,
        kind_warn_days=DEFAULT_KIND_WARN_DAYS,
        probe_github_expiry=False,
        now=now_fixed,
    )
    sso2 = [c for c in narrowed.credentials if c.kind == KIND_AWS_SSO]
    assert sso2 and sso2[0].status == STATUS_VALID


def test_detect_aws_sso_expired(fake_home: Path, now_fixed: datetime) -> None:
    _write_sso(fake_home, "a", _iso(now_fixed - timedelta(days=2)))
    out = detect_aws_sso(fake_home, warn_threshold_days=7, now=now_fixed)
    assert out[0].status == STATUS_EXPIRED
    assert out[0].expires_in_seconds is not None
    assert out[0].expires_in_seconds < 0


def test_detect_aws_sso_unknown_when_no_field(fake_home: Path, now_fixed: datetime) -> None:
    _write_sso(fake_home, "a", None)
    out = detect_aws_sso(fake_home, warn_threshold_days=7, now=now_fixed)
    assert out[0].status == STATUS_UNKNOWN
    assert out[0].expires_at is None


def test_detect_aws_sso_skips_corrupt(fake_home: Path, now_fixed: datetime) -> None:
    cache = fake_home / ".aws" / "sso" / "cache"
    cache.mkdir(parents=True)
    (cache / "bad.json").write_text("not json", encoding="utf-8")
    _write_sso(fake_home, "good", _iso(now_fixed + timedelta(days=30)))
    out = detect_aws_sso(fake_home, warn_threshold_days=7, now=now_fixed)
    assert len(out) == 1
    assert out[0].source.endswith("good.json")


def test_detect_aws_sso_empty_when_no_dir(fake_home: Path, now_fixed: datetime) -> None:
    assert detect_aws_sso(fake_home, warn_threshold_days=7, now=now_fixed) == []


def test_detect_github_finds_users_no_probe(fake_home: Path, now_fixed: datetime) -> None:
    hosts_dir = fake_home / ".config" / "gh"
    hosts_dir.mkdir(parents=True)
    (hosts_dir / "hosts.yml").write_text(
        "github.com:\n  users:\n    alice:\n      git_protocol: ssh\n    bob:\n      git_protocol: https\n",
        encoding="utf-8",
    )
    out = detect_github(fake_home, warn_threshold_days=7, now=now_fixed, probe_expiry=False)
    assert {c.identifier for c in out} == {"github.com/alice", "github.com/bob"}
    # probe_expiry=False → 모두 valid (감지됐으니까)
    assert all(c.status == STATUS_VALID for c in out)
    assert all(c.expires_at is None for c in out)


def test_detect_github_empty_when_no_file(fake_home: Path, now_fixed: datetime) -> None:
    assert detect_github(fake_home, warn_threshold_days=7, now=now_fixed, probe_expiry=False) == []


def test_detect_github_active_only_no_users_section(fake_home: Path, now_fixed: datetime) -> None:
    """users 섹션이 없는 host 도 '(active)' 로 1건 등록."""
    hosts_dir = fake_home / ".config" / "gh"
    hosts_dir.mkdir(parents=True)
    (hosts_dir / "hosts.yml").write_text("github.com:\n  some_other_key: x\n", encoding="utf-8")
    out = detect_github(fake_home, warn_threshold_days=7, now=now_fixed, probe_expiry=False)
    assert len(out) == 1
    assert out[0].identifier == "github.com/(active)"


def test_detect_claude_oauth_finds_account(fake_home: Path, now_fixed: datetime) -> None:
    (fake_home / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "u@x.test", "accountUuid": "uuid-1"}}),
        encoding="utf-8",
    )
    (fake_home / ".claude-edward.json").write_text(
        json.dumps({"oauthAccount": {"accountUuid": "uuid-2"}}),
        encoding="utf-8",
    )
    out = detect_claude_oauth(fake_home, warn_threshold_days=7, now=now_fixed)
    assert len(out) == 2
    idents = {c.identifier for c in out}
    assert "u@x.test" in idents
    assert "uuid-2" in idents  # email 없으면 accountUuid 로
    assert all(c.kind == KIND_CLAUDE_OAUTH for c in out)
    assert all(c.status == STATUS_VALID for c in out)
    assert all(c.expires_at is None for c in out)


def test_detect_claude_oauth_skips_no_oauth_field(fake_home: Path, now_fixed: datetime) -> None:
    """oauthAccount 키 없는 claude*.json 은 skip."""
    (fake_home / ".claude.json").write_text(json.dumps({"theme": "auto"}), encoding="utf-8")
    out = detect_claude_oauth(fake_home, warn_threshold_days=7, now=now_fixed)
    assert out == []


def test_detect_claude_oauth_skips_corrupt(fake_home: Path, now_fixed: datetime) -> None:
    (fake_home / ".claude.json").write_text("{not json", encoding="utf-8")
    (fake_home / ".claude-good.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "ok@x.test"}}),
        encoding="utf-8",
    )
    out = detect_claude_oauth(fake_home, warn_threshold_days=7, now=now_fixed)
    assert len(out) == 1
    assert out[0].identifier == "ok@x.test"


def test_collect_credentials_envelope_schema(fake_home: Path, now_fixed: datetime) -> None:
    """collect_credentials 의 report schema v1 검증."""
    _write_sso(fake_home, "a", _iso(now_fixed + timedelta(days=30)))
    report = collect_credentials(
        home=fake_home,
        warn_threshold_days=14,
        probe_github_expiry=False,
        now=now_fixed,
    )
    assert report.schema_version == SCHEMA_VERSION
    assert report.warn_threshold_days == 14
    assert report.generated_at == _iso(now_fixed)
    assert len(report.credentials) == 1

    # JSON 직렬화 — to_dict() 가 schema_version=1 envelope dict 반환
    envelope = report.to_dict()
    assert envelope["schema_version"] == SCHEMA_VERSION
    assert isinstance(envelope["credentials"], list)
    c = envelope["credentials"][0]
    assert isinstance(c, dict)
    assert set(c.keys()) == {
        "kind",
        "identifier",
        "source",
        "expires_at",
        "expires_in_seconds",
        "status",
    }


def test_collect_credentials_all_three_kinds(fake_home: Path, now_fixed: datetime) -> None:
    """3 kind 모두 등록된 경우 report 에 합쳐서 반환."""
    _write_sso(fake_home, "a", _iso(now_fixed + timedelta(days=2)))  # expiring
    hosts_dir = fake_home / ".config" / "gh"
    hosts_dir.mkdir(parents=True)
    (hosts_dir / "hosts.yml").write_text(
        "github.com:\n  users:\n    alice: {}\n",
        encoding="utf-8",
    )
    (fake_home / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "u@x.test"}}),
        encoding="utf-8",
    )

    report = collect_credentials(
        home=fake_home,
        warn_threshold_days=DEFAULT_WARN_THRESHOLD_DAYS,
        probe_github_expiry=False,
        now=now_fixed,
    )
    kinds = sorted(c.kind for c in report.credentials)
    assert kinds == [KIND_AWS_SSO, KIND_CLAUDE_OAUTH, KIND_GITHUB]
    statuses = [c.status for c in report.credentials]
    assert STATUS_EXPIRING in statuses
    assert statuses.count(STATUS_VALID) == 2


def test_collect_credentials_warn_days_override(fake_home: Path, now_fixed: datetime) -> None:
    """--warn-days 1 (좁힘) → 3일 남은 token 이 valid 로 분류."""
    _write_sso(fake_home, "a", _iso(now_fixed + timedelta(days=3)))
    report = collect_credentials(
        home=fake_home,
        warn_threshold_days=1,
        probe_github_expiry=False,
        now=now_fixed,
    )
    assert report.credentials[0].status == STATUS_VALID
