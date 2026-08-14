"""`anvyc creds status` CLI 가 per-kind expiring 임계를 적용하는지 (doctor 와 정합).

doctor check(`checks/creds_expiry.py`)는 `DEFAULT_KIND_WARN_DAYS` + config override 를
merge 해 `kind_warn_days` 로 넘긴다. 반면 CLI 는 단일 `--warn-days` 만 넘겨, 같은 자격을
두 경로가 다르게 분류했다 — 사람이 보는 표는 `expiring`, statusline/doctor 판정은 `OK`.

2026-08-14 실측: 방금 로그인해 56분 남은 aws_sso 세션이 표에서는 `expiring=2` 로 나오고
statusline 은 `creds sev=OK` 였다. 값이 틀린 게 아니라 표시와 정책이 어긋난 상태다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anvyc.cli import app
from anvyc.core.config import AnvycConfig
from anvyc.core.creds import (
    DEFAULT_KIND_WARN_DAYS,
    KIND_AWS_SSO,
    STATUS_EXPIRING,
    STATUS_VALID,
    resolve_kind_warn_days,
)


def _write_sso(home: Path, minutes_left: int) -> None:
    """만료가 now+minutes_left 인 SSO 세션 캐시 1건.

    CLI 는 `--now` 를 노출하지 않으므로 실시간 기준으로 쓴다 — 분 단위 여유라
    테스트 실행 시간에 흔들리지 않는다.
    """
    cache = home / ".aws" / "sso" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    exp = datetime.now(UTC) + timedelta(minutes=minutes_left)
    payload = {
        "startUrl": "https://x.awsapps.com/start",
        "clientId": "x",
        "clientSecret": "y",
        "expiresAt": exp.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (cache / "sess.json").write_text(json.dumps(payload), encoding="utf-8")


def _aws_statuses(home: Path) -> list[str]:
    """CLI 를 --json 으로 돌려 aws_sso 자격의 status 목록을 반환."""
    result = CliRunner().invoke(
        app, ["creds", "status", "--json", "--no-probe", "--home", str(home)]
    )
    assert result.exit_code == 0, result.output
    creds = json.loads(result.output)["credentials"]
    return [c["status"] for c in creds if c["kind"] == KIND_AWS_SSO]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def default_config(monkeypatch: pytest.MonkeyPatch) -> AnvycConfig:
    """CLI 의 config 로드를 기본값으로 고정 — 머신의 실제 anvyc.yaml 과 무관하게 한다.

    cli.py 는 `load_anvyc_config` 를 함수 지역 import 로 가져오므로, 바인딩이 아니라
    원본 모듈(`anvyc.core.config`)을 갈아끼워야 한다.
    """
    cfg = AnvycConfig()
    monkeypatch.setattr("anvyc.core.config.load_anvyc_config", lambda *a: cfg)
    return cfg


def test_resolve_kind_warn_days_merges_overrides_over_defaults() -> None:
    """초 단위 override 를 일 단위로 바꿔 코드 기본값 위에 얹는다 — doctor·CLI 공용."""
    assert resolve_kind_warn_days({}) == DEFAULT_KIND_WARN_DAYS
    merged = resolve_kind_warn_days({KIND_AWS_SSO: 1800})
    assert merged[KIND_AWS_SSO] == pytest.approx(1800 / 86400)


def test_cli_aws_sso_beyond_window_is_valid(home: Path, default_config: AnvycConfig) -> None:
    """잔여 56분 aws_sso → valid.

    기본 `--warn-days 7` 이 aws_sso 에도 적용되면 expiring 이 된다 — 그게 고치려는 버그다.
    """
    _write_sso(home, minutes_left=56)
    assert _aws_statuses(home) == [STATUS_VALID]


def test_cli_aws_sso_inside_window_is_expiring(home: Path, default_config: AnvycConfig) -> None:
    """경계 앵커 — 잔여 10분(15분 윈도 안)은 여전히 expiring.

    이게 없으면 "aws_sso 는 무조건 valid" 인 구현도 위 시험을 통과한다.
    """
    _write_sso(home, minutes_left=10)
    assert _aws_statuses(home) == [STATUS_EXPIRING]


def test_cli_honors_config_override(home: Path, default_config: AnvycConfig) -> None:
    """`doctor.creds_expiry.warn_thresholds` 가 CLI 에도 반영 — doctor 와 같은 경로.

    임계를 기본값(15분)보다 **좁혀야** 세 상태가 구분된다. 잔여 10분 + override 5분:
      - 버그(7d 적용)            → expiring  (실패해야 함)
      - override 무시(기본 15분) → expiring  (배선 누락도 실패해야 함)
      - override 반영(5분)       → valid     (기대)
    넓히는 방향(예: 60분)으로 잡으면 세 경우가 모두 expiring 이라 시험이 공허해진다.
    """
    default_config.doctor.creds_warn_thresholds = {KIND_AWS_SSO: 300}  # 5분
    _write_sso(home, minutes_left=10)
    assert _aws_statuses(home) == [STATUS_VALID]
