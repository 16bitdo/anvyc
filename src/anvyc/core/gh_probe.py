"""GitHub 토큰 만료 probe — `anvyc gh account --probe` 전용 (opt-in, 네트워크).

`aws_probe.py` 의 sibling 모듈. doctor / collect_accounts 는 이 모듈을
import 하지 않는다 (오프라인 보장). 오직 `--probe` 플래그로 명시 요청 시만 호출.

토큰 값은 읽거나 반환하거나 로그하지 않는다 — `GH_CONFIG_DIR` 만 설정해
gh CLI 가 해당 계정 dir 의 keyring/OAuth 를 사용하도록 위임 (rule 26).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from anvyc.core.creds import DEFAULT_WARN_THRESHOLD_DAYS, _classify


@dataclass(frozen=True)
class GhProbeResult:
    """단일 GitHub 계정 토큰 만료 probe 결과.

    status:
        ``"valid"``    — 만료까지 warn_threshold_days 초과.
        ``"expiring"`` — warn_threshold_days 이내 만료 임박.
        ``"expired"``  — 이미 만료.
        ``"unknown"``  — 헤더 없음 / gh 미설치 / 오류 — graceful.
    expires_at:
        ISO8601 UTC 문자열 (e.g. ``"2099-01-01T00:00:00Z"``), 또는 ``None``.
    """

    status: str
    expires_at: str | None


# GitHub 응답 헤더 패턴 — creds.py _detect_github_token_expiry 와 동일
_EXPIRY_RE = re.compile(r"^[Xx]-[Gg]it[Hh]ub-[Tt]oken-[Ee]xpiration:\s*(.+)$")


def _parse_expiry_from_stdout(stdout: str) -> str | None:
    """gh api -i stdout 에서 X-GitHub-Token-Expiration 헤더를 추출해 ISO8601 변환.

    GitHub 헤더 형식: ``X-GitHub-Token-Expiration: 2026-05-25 12:34:56 UTC``
    반환: ``"2026-05-25T12:34:56Z"`` 또는 ``None`` (헤더 없음 / parse 실패).

    creds.py `_detect_github_token_expiry` 의 파싱 로직을 그대로 재현.
    토큰 값은 절대 읽지 않는다.
    """
    for line in stdout.splitlines():
        m = _EXPIRY_RE.match(line)
        if m:
            raw = m.group(1).strip()
            try:
                dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S %Z")
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                # 이미 ISO 형식이거나 알 수 없는 형식 — 그대로 반환 (best-effort)
                return raw
    return None


def probe_token_expiry(
    config_dir: Path,
    host: str,
    user: str,
    *,
    timeout: float = 8.0,
) -> GhProbeResult:
    """``gh api -i user --hostname <host> --user <user>`` 실행 후 만료 헤더 분류.

    ``GH_CONFIG_DIR=<config_dir>`` env 를 설정해 해당 계정의 gh config dir 을
    사용한다 — 토큰 값 자체는 읽거나 반환하거나 로그하지 않는다 (rule 26).

    Parameters
    ----------
    config_dir:
        gh config dir (e.g. ``~/.config/gh-16bitdo``). GH_CONFIG_DIR 로 주입.
    host:
        GitHub hostname (e.g. ``"github.com"``).
    user:
        GitHub username (e.g. ``"16bitdo"``).
    timeout:
        subprocess timeout (초). 기본 8.0.

    Returns
    -------
    GhProbeResult
        네트워크 오류 / gh 미설치 / 비정상 종료 / 헤더 없음 → ``("unknown", None)``.
        예외를 절대 raise 하지 않는다.
    """
    env = {**os.environ, "GH_CONFIG_DIR": str(config_dir)}
    cmd = ["gh", "api", "-i", "user", "--hostname", host, "--user", user]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return GhProbeResult(status="unknown", expires_at=None)

    if proc.returncode != 0:
        return GhProbeResult(status="unknown", expires_at=None)

    expires_at = _parse_expiry_from_stdout(proc.stdout)
    if expires_at is None:
        return GhProbeResult(status="unknown", expires_at=None)

    now = datetime.now(UTC)
    _seconds, status = _classify(
        expires_at,
        warn_threshold_days=DEFAULT_WARN_THRESHOLD_DAYS,
        now=now,
    )
    return GhProbeResult(status=status, expires_at=expires_at)
