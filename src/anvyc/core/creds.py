"""Credentials lifecycle — CP-5 (anvyc#30) 1/3.

GitHub PAT / AWS session / Claude OAuth 토큰의 발견 + 만료시각 추출 + status
분류. read-only — write (rotate) 는 3/3 PR.

Detection 전략 (1/3 MVP — 1 kind 당 1 source 만):
- **AWS SSO**: `<home>/.aws/sso/cache/*.json` 의 `expiresAt` (ISO8601). 직접
  추출 가능 → status (valid/expiring/expired) 명확.
- **GitHub**: `<home>/.config/gh/hosts.yml` 의 user 발견 + (선택) `gh api -i`
  의 `X-GitHub-Token-Expiration` 헤더 parse. 헤더 부재 시 'unknown'
  (classic OAuth token 은 만료 없음).
- **Claude OAuth**: `<home>/.claude*.json` 의 `oauthAccount` 필드 존재로
  detection. 실제 access/refresh token 은 별도 (keychain 등) → 1/3 에서는
  expiry='unknown' + status='valid'(detected).

Schema v1 (`schema_version: 1`):

    {
      "schema_version": 1,
      "generated_at": "ISO8601 UTC",
      "warn_threshold_days": 7,
      "credentials": [
        {
          "kind": "aws_sso" | "github" | "claude_oauth",
          "identifier": "<profile/start_url/email>",
          "source": "<file path 또는 'gh CLI'>",
          "expires_at": "ISO8601 UTC | null",
          "expires_in_seconds": int | null,
          "status": "valid" | "expiring" | "expired" | "unknown"
        },
        ...
      ]
    }

후속 PR
- 2/3: doctor 의 신규 check `creds_expiry_within_7d` 통합 (1/3 의 collect_
  credentials 호출). CP-3 scheduler 가 자연 호출.
- 3/3: `anvyc creds rotate <kind>` (destructive — op CLI wrapper).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_WARN_THRESHOLD_DAYS = 7

KIND_AWS_SSO = "aws_sso"
KIND_GITHUB = "github"
KIND_CLAUDE_OAUTH = "claude_oauth"

STATUS_VALID = "valid"
STATUS_EXPIRING = "expiring"
STATUS_EXPIRED = "expired"
STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class CredentialStatus:
    """단일 credential 의 발견 + 만료 상태."""

    kind: str
    identifier: str
    source: str
    expires_at: str | None
    expires_in_seconds: int | None
    status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CredentialsReport:
    """`collect_credentials` envelope (schema v1)."""

    schema_version: int
    generated_at: str
    warn_threshold_days: int
    credentials: list[CredentialStatus]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "warn_threshold_days": self.warn_threshold_days,
            "credentials": [c.to_dict() for c in self.credentials],
        }


# ===== Rotate (CP-5 3/3) =====
#
# 3 kind 의 자격 회전 — native re-auth 우선. 1Password CLI(`op`) 통합은 후속
# polish (사용자가 명시적으로 PAT 를 op 에 저장한 경우만 의미). 본 1차 구현
# 은 browser-based OAuth refresh 가 더 안전한 다수 케이스를 다룬다.
#
# rule 26-secrets-1password 준수: token 본문을 stdout/stderr 로 출력하지
# 않음. subprocess 호출은 caller 의 PATH 의 외부 명령에 위임 (token 내용
# 미캡처). op CLI 통합은 후속 polish (--from-op REF 형태로 별도 도입).

ROTATE_KINDS = (KIND_AWS_SSO, KIND_GITHUB, KIND_CLAUDE_OAUTH)


class RotateError(ValueError):
    """rotate 입력/실행 오류."""


@dataclass(frozen=True)
class RotatePlan:
    """`rotate --dry-run` 의 plan 출력."""

    kind: str
    command: list[str]  # 실 실행될 외부 명령 (빈 list = 사용자 수동 조치 안내)
    description: str
    warnings: list[str]


@dataclass(frozen=True)
class RotateResult:
    """`rotate` 실 실행 결과."""

    kind: str
    executed: bool                 # subprocess 가 실제 호출됐는지
    return_code: int | None        # subprocess exit code (executed=False 면 None)
    stdout_tail: str               # 마지막 N bytes (token 노출 회피 위해 짧게)
    stderr_tail: str
    note: str                      # claude_oauth 같이 안내만 한 경우의 메시지


def plan_rotate(kind: str) -> RotatePlan:
    """3 kind 별 rotation plan.

    Raises:
      RotateError: kind 가 지원 범위 밖.
    """
    if kind not in ROTATE_KINDS:
        raise RotateError(
            f"unsupported kind: {kind!r}. supported: {', '.join(ROTATE_KINDS)}"
        )

    if kind == KIND_AWS_SSO:
        return RotatePlan(
            kind=kind,
            command=["aws", "sso", "login"],
            description="AWS SSO 브라우저 인증 — 새 access token 발급 후 ~/.aws/sso/cache/ 에 저장.",
            warnings=[
                "브라우저가 열림 — 활성 SSO start_url 의 default profile 기준.",
                "여러 SSO 인스턴스가 있으면 'aws sso login --profile <name>' 으로 명시 권장 (본 명령은 default).",
            ],
        )
    if kind == KIND_GITHUB:
        return RotatePlan(
            kind=kind,
            command=["gh", "auth", "refresh"],
            description="GitHub OAuth refresh — 활성 host/user 의 token 재발급.",
            warnings=[
                "gh CLI 가 관리하는 OAuth 만 영향 — 별도 PAT 는 사용자가 새로 발급 + `gh auth login --with-token` 필요.",
                "1Password 저장 PAT 의 경우 별도 wrapper 가 필요 (후속 polish: --from-op REF).",
            ],
        )
    # KIND_CLAUDE_OAUTH — Claude Code UI 에서 re-login 필요
    return RotatePlan(
        kind=kind,
        command=[],  # 사용자 수동 조치
        description="Claude Code UI 에서 re-login 필요 — anvyc 가 직접 회전 불가.",
        warnings=[
            "1) Claude Code 종료 후 재시작 → OAuth 흐름 자동 재발급 가능.",
            "2) 또는 https://claude.com/login 에서 web 재로그인 → ~/.claude.json 갱신 자동.",
            "3) anvyc CLI 는 직접 token 갱신 안 함 (security 경계 — rule 26).",
        ],
    )


def rotate_credential(kind: str, *, timeout_seconds: int = 300) -> RotateResult:
    """plan_rotate(kind).command 를 실 실행.

    - command 가 빈 list (claude_oauth) → executed=False + 안내 메시지만.
    - 외부 명령 호출 실패 (FileNotFoundError 등) → RotateError raise.
    - subprocess exit code 그대로 반환 (caller 가 0/non-0 판단).

    Args:
      kind: 회전 대상.
      timeout_seconds: subprocess timeout (browser 인증 사용자 대기 고려, 기본 5분).

    Note:
      stdout/stderr 는 마지막 2 KiB 만 capture — token 본문이 외부 명령
      output 에 새지 않도록 짧게 (rule 26). 본 함수는 token 을 직접
      다루지 않음 — 외부 명령에 위임.
    """
    plan = plan_rotate(kind)

    if not plan.command:
        return RotateResult(
            kind=kind,
            executed=False,
            return_code=None,
            stdout_tail="",
            stderr_tail="",
            note=plan.description + " (사용자 수동 조치 필요)",
        )

    try:
        proc = subprocess.run(
            plan.command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RotateError(
            f"외부 명령 부재: {plan.command[0]} — 설치 후 재시도. ({exc})"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RotateError(
            f"rotation timeout (>{timeout_seconds}s): {' '.join(plan.command)}. "
            f"browser 인증 사용자 응답 지연 가능 — 수동 완료 후 'anvyc creds status' 확인."
        ) from exc

    # token 본문 노출 회피 위해 tail 만 (각 2 KiB)
    return RotateResult(
        kind=kind,
        executed=True,
        return_code=proc.returncode,
        stdout_tail=proc.stdout[-2048:] if proc.stdout else "",
        stderr_tail=proc.stderr[-2048:] if proc.stderr else "",
        note=plan.description,
    )


def _classify(expires_at: str | None, *, warn_threshold_days: int, now: datetime) -> tuple[int | None, str]:
    """expires_at ISO8601 → (expires_in_seconds, status).

    expires_at=None → (None, "unknown"). 호출측이 detected_active 여부에
    따라 'valid' 재분류 가능.
    """
    if expires_at is None:
        return None, STATUS_UNKNOWN
    try:
        dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None, STATUS_UNKNOWN
    seconds_remaining = int((dt - now).total_seconds())
    if seconds_remaining <= 0:
        return seconds_remaining, STATUS_EXPIRED
    if seconds_remaining < warn_threshold_days * 86400:
        return seconds_remaining, STATUS_EXPIRING
    return seconds_remaining, STATUS_VALID


def detect_aws_sso(home: Path, *, warn_threshold_days: int, now: datetime) -> list[CredentialStatus]:
    """`<home>/.aws/sso/cache/*.json` 에서 `expiresAt` 추출."""
    out: list[CredentialStatus] = []
    cache_dir = home / ".aws" / "sso" / "cache"
    if not cache_dir.is_dir():
        return out
    for f in sorted(cache_dir.glob("*.json")):
        try:
            with f.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        expires_at = data.get("expiresAt")
        start_url = data.get("startUrl") or "(no startUrl)"
        seconds, status = _classify(expires_at, warn_threshold_days=warn_threshold_days, now=now)
        out.append(
            CredentialStatus(
                kind=KIND_AWS_SSO,
                identifier=start_url,
                source=str(f),
                expires_at=expires_at,
                expires_in_seconds=seconds,
                status=status,
            )
        )
    return out


def _parse_gh_hosts(hosts_yml: Path) -> dict[str, list[str]]:
    """간이 YAML parser — `<host>:\\n  users:\\n    <user>:\\n      ...` 만 인식.

    가정: gh CLI 의 `hosts.yml` 형식. PyYAML 의존 회피를 위한 minimal parser.
    파싱 실패 시 빈 dict.
    """
    if not hosts_yml.is_file():
        return {}
    result: dict[str, list[str]] = {}
    try:
        text = hosts_yml.read_text(encoding="utf-8")
    except OSError:
        return {}
    current_host: str | None = None
    in_users = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9._-]+):\s*$", line)
        if m and not line.startswith(" "):
            current_host = m.group(1)
            result[current_host] = []
            in_users = False
            continue
        if current_host is None:
            continue
        if re.match(r"^  users:\s*$", line):
            in_users = True
            continue
        if in_users:
            m2 = re.match(r"^    ([A-Za-z0-9._-]+):\s*$", line)
            if m2:
                result[current_host].append(m2.group(1))
                continue
            # users block end (indentation 감소)
            if line and not line.startswith("    "):
                in_users = False
    return result


def _detect_github_token_expiry(host: str, user: str | None) -> str | None:
    """gh CLI 의 `gh api -i user --hostname <host>` 응답 헤더에서 추출.

    X-GitHub-Token-Expiration 헤더가 있으면 ISO8601 변환해 반환; 없으면 None.
    gh 미설치 / 호출 실패 시도 None (검출 안 됨 = unknown 으로 처리).
    """
    cmd = ["gh", "api", "-i", "user", "--hostname", host]
    if user:
        cmd += ["--user", user]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    # 헤더: `X-GitHub-Token-Expiration: 2026-...` 또는 `X-Github-Token-Expiration: ...`
    for line in proc.stdout.splitlines():
        m = re.match(r"^[Xx]-[Gg]it[Hh]ub-[Tt]oken-[Ee]xpiration:\s*(.+)$", line)
        if m:
            raw = m.group(1).strip()
            # GitHub 은 "2026-05-25 12:34:56 UTC" 같은 형식 사용 — ISO 변환
            try:
                dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S %Z")
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                # 이미 ISO 형식이면 그대로
                return raw
    return None


def detect_github(home: Path, *, warn_threshold_days: int, now: datetime, probe_expiry: bool = True) -> list[CredentialStatus]:
    """`<home>/.config/gh/hosts.yml` 에서 host/user 발견."""
    out: list[CredentialStatus] = []
    hosts_yml = home / ".config" / "gh" / "hosts.yml"
    hosts_map = _parse_gh_hosts(hosts_yml)
    if not hosts_map:
        return out
    for host, users in sorted(hosts_map.items()):
        if not users:
            users = ["(active)"]
        for user in users:
            expires_at: str | None = None
            if probe_expiry:
                expires_at = _detect_github_token_expiry(host, user if user != "(active)" else None)
            seconds, status = _classify(expires_at, warn_threshold_days=warn_threshold_days, now=now)
            # expires_at 미발견이고 user 가 감지됐으면 valid (unknown 보다 적극)
            if expires_at is None:
                status = STATUS_VALID
            out.append(
                CredentialStatus(
                    kind=KIND_GITHUB,
                    identifier=f"{host}/{user}",
                    source=str(hosts_yml),
                    expires_at=expires_at,
                    expires_in_seconds=seconds,
                    status=status,
                )
            )
    return out


def detect_claude_oauth(home: Path, *, warn_threshold_days: int, now: datetime) -> list[CredentialStatus]:
    """`<home>/.claude*.json` 의 `oauthAccount` 발견."""
    out: list[CredentialStatus] = []
    for f in sorted(home.glob(".claude*.json")):
        if not f.is_file():
            continue
        try:
            with f.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        oauth = data.get("oauthAccount")
        if not isinstance(oauth, dict):
            continue
        identifier = oauth.get("emailAddress") or oauth.get("accountUuid") or "(unknown)"
        # 1/3 MVP — Claude OAuth expiry 는 직접 노출 안 됨, 추후 keychain 접근
        # 시 보강. detected_active = valid + expiry unknown.
        out.append(
            CredentialStatus(
                kind=KIND_CLAUDE_OAUTH,
                identifier=str(identifier),
                source=str(f),
                expires_at=None,
                expires_in_seconds=None,
                status=STATUS_VALID,
            )
        )
    return out


def collect_credentials(
    *,
    home: Path | None = None,
    warn_threshold_days: int = DEFAULT_WARN_THRESHOLD_DAYS,
    probe_github_expiry: bool = True,
    now: datetime | None = None,
) -> CredentialsReport:
    """3 kind credential detection 묶음 + schema v1 envelope 반환.

    Args:
      home: 검사 root (기본 `Path.home()`). 테스트 주입용.
      warn_threshold_days: expiring 분류 threshold (기본 7).
      probe_github_expiry: True 면 `gh api` 호출로 expiry 헤더 추출. CI /
        offline 환경에선 False 권장.
      now: 만료 비교 기준 (기본 datetime.now(UTC)).

    Returns:
      `CredentialsReport` (typed) — JSON 으로 직렬화하려면 `.to_dict()`.
    """
    h = home or Path.home()
    n = now or datetime.now(tz=UTC)
    creds: list[CredentialStatus] = []
    creds.extend(detect_aws_sso(h, warn_threshold_days=warn_threshold_days, now=n))
    creds.extend(
        detect_github(
            h, warn_threshold_days=warn_threshold_days, now=n, probe_expiry=probe_github_expiry
        )
    )
    creds.extend(detect_claude_oauth(h, warn_threshold_days=warn_threshold_days, now=n))

    return CredentialsReport(
        schema_version=SCHEMA_VERSION,
        generated_at=n.strftime("%Y-%m-%dT%H:%M:%SZ"),
        warn_threshold_days=warn_threshold_days,
        credentials=creds,
    )


# 환경 변수 export 가 노출되어 있는지 확인용 (op CLI 의존 점검 — 후속 3/3 에서 활용)
def _has_op_cli() -> bool:
    """1Password CLI 가 PATH 에 있는지 (3/3 rotate 의존 체크용)."""
    return os.system("command -v op >/dev/null 2>&1") == 0
