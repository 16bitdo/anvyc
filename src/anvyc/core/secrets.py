"""Secret Broker — CP-15 Phase 1 (read-only).

`anvyc.yaml` 의 `secrets:` 레지스트리(값 없는 핸들)를 backend 별로 verify 하고
schema v1 report 로 합성한다. anvyc 는 secret 평문을 보유/출력하지 않는다 —
backend(op/sops/keychain/aws-vault)에 위임하며 probe 는 **exit code / 비-secret
메타데이터(profile 이름)만** 읽는다 (rule 26-secrets-1password).

Phase 1 범위: detection + handle 검증 + resolvability probe + status 분류.
write(add/get/inject-wire/passphrase)는 Phase 2+ (DESIGN §39 / cp-15-secret-broker.md §9).

Report schema v1 (`schema_version: 1`):

    {
      "schema_version": 1,
      "generated_at": "ISO8601 UTC",
      "entries": [
        {
          "name": "<논리 이름>",
          "backend": "op|sops|keychain|aws-vault",
          "reference": "<비-secret 핸들 표현>",
          "status": "ok|unresolved|invalid|unknown",
          "detail": "<사람용 설명 — 값 미포함>"
        }, ...
      ]
    }
"""
from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from anvyc.core.config import SecretEntry, load_anvyc_config

SCHEMA_VERSION = 1
_PROBE_TIMEOUT_S = 6

BACKEND_OP = "op"
BACKEND_SOPS = "sops"
BACKEND_KEYCHAIN = "keychain"
BACKEND_AWS_VAULT = "aws-vault"
KNOWN_BACKENDS = (BACKEND_OP, BACKEND_SOPS, BACKEND_KEYCHAIN, BACKEND_AWS_VAULT)

STATUS_OK = "ok"                  # 핸들 유효 + (probe 시) resolve 가능
STATUS_UNRESOLVED = "unresolved"  # 핸들은 형식 OK 이나 backend 에서 resolve 실패
STATUS_INVALID = "invalid"        # backend 별 필수 핸들 필드 누락
STATUS_UNKNOWN = "unknown"        # 미지 backend 또는 backend CLI 미설치/미인증 (검증 skip)


@dataclass(frozen=True)
class SecretStatus:
    """단일 secret entry 의 verify 결과 (값 미포함)."""

    name: str
    backend: str
    reference: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SecretsReport:
    """`collect_secrets` envelope (schema v1)."""

    schema_version: int
    generated_at: str
    entries: list[SecretStatus]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "entries": [e.to_dict() for e in self.entries],
        }

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entries:
            out[e.status] = out.get(e.status, 0) + 1
        return out


def reference_of(entry: SecretEntry) -> str:
    """backend 별 비-secret 핸들 문자열. 표시/와이어링용 (값 아님)."""
    if entry.backend == BACKEND_OP:
        return entry.ref or "(no ref)"
    if entry.backend == BACKEND_SOPS:
        base = f"sops:{entry.file or '(no file)'}"
        return f"{base}#{entry.key}" if entry.key else base
    if entry.backend == BACKEND_KEYCHAIN:
        return f"keychain:{entry.service or '?'}/{entry.account or '?'}"
    if entry.backend == BACKEND_AWS_VAULT:
        return f"aws-vault:{entry.profile or '?'}"
    return f"{entry.backend}:?"


def _handle_error(entry: SecretEntry) -> str | None:
    """backend 별 필수 핸들 필드 누락 검사. OK 면 None."""
    if entry.backend == BACKEND_OP and not entry.ref:
        return "op backend 는 'ref' (op://<vault>/<item>/<field>) 필수"
    if entry.backend == BACKEND_SOPS and not entry.file:
        return "sops backend 는 'file' (SOPS 파일 경로) 필수"
    if entry.backend == BACKEND_KEYCHAIN and not (entry.service and entry.account):
        return "keychain backend 는 'service' + 'account' 필수"
    if entry.backend == BACKEND_AWS_VAULT and not entry.profile:
        return "aws-vault backend 는 'profile' 필수"
    return None


def _run_rc(cmd: list[str]) -> int | None:
    """외부 명령 exit code 만 반환. 미설치/오류 시 None. stdout/stderr 는 버린다."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=_PROBE_TIMEOUT_S, check=False
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    return proc.returncode


def _probe_op(entry: SecretEntry) -> tuple[str, str]:
    if not shutil.which("op"):
        return STATUS_UNKNOWN, "op CLI 미설치 — 검증 skip (brew install 1password-cli)"
    if _run_rc(["op", "whoami"]) != 0:
        return STATUS_UNKNOWN, "op 미인증 (op signin) — 검증 skip"
    # 값(stdout)은 _run_rc 가 폐기 — exit code 만으로 resolve 여부 판정
    rc = _run_rc(["op", "read", "--no-newline", entry.ref or ""])
    if rc == 0:
        return STATUS_OK, "op reference resolve 가능"
    return STATUS_UNRESOLVED, "op:// reference resolve 실패 (vault/item/field 확인)"


def _probe_sops(entry: SecretEntry) -> tuple[str, str]:
    if not shutil.which("sops"):
        return STATUS_UNKNOWN, "sops 미설치 — 검증 skip (brew install sops)"
    path = Path(entry.file or "").expanduser()
    if not path.is_file():
        return STATUS_UNRESOLVED, f"SOPS 파일 없음: {entry.file}"
    # 실복호화는 apply 시점 — Phase 1 은 SOPS metadata 존재만 확인 (key prompt 회피)
    from anvyc.core.sops import is_sops_encrypted

    if not is_sops_encrypted(path):
        return STATUS_UNRESOLVED, "SOPS 암호문이 아님 (sops encrypt 필요)"
    return STATUS_OK, "SOPS 파일 존재 (복호화는 apply 시 age 키 사용)"


def _probe_keychain(entry: SecretEntry) -> tuple[str, str]:
    if platform.system() != "Darwin" or not shutil.which("security"):
        return STATUS_UNKNOWN, "keychain(macOS security) 미지원 환경 — 검증 skip"
    # -w (값 출력) 미사용 — 존재 여부만 (exit code). 값 비노출.
    rc = _run_rc(
        ["security", "find-generic-password", "-s", entry.service or "", "-a", entry.account or ""]
    )
    if rc == 0:
        return STATUS_OK, "keychain 항목 존재"
    return STATUS_UNRESOLVED, "keychain 항목 없음 (service/account 확인)"


def _probe_aws_vault(entry: SecretEntry) -> tuple[str, str]:
    if not shutil.which("aws-vault"):
        return STATUS_UNKNOWN, "aws-vault 미설치 — 검증 skip"
    # profile 이름은 비-secret — list 출력에서 존재만 확인
    try:
        proc = subprocess.run(
            ["aws-vault", "list", "--profiles"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return STATUS_UNKNOWN, "aws-vault list 실패 — 검증 skip"
    if proc.returncode != 0:
        return STATUS_UNKNOWN, "aws-vault list 실패 — 검증 skip"
    profiles = {ln.strip() for ln in proc.stdout.splitlines() if ln.strip()}
    if entry.profile in profiles:
        return STATUS_OK, "aws-vault profile 존재"
    return STATUS_UNRESOLVED, f"aws-vault profile 없음: {entry.profile}"


_PROBES = {
    BACKEND_OP: _probe_op,
    BACKEND_SOPS: _probe_sops,
    BACKEND_KEYCHAIN: _probe_keychain,
    BACKEND_AWS_VAULT: _probe_aws_vault,
}


def verify_entry(entry: SecretEntry, *, probe: bool = True) -> SecretStatus:
    """단일 entry 의 backend / 핸들 / (선택) resolvability 검증.

    probe=False (doctor / CI offline): 미지 backend + 핸들 필드 누락만 검사,
    외부 명령 호출 없음. probe=True (`secret list`): backend CLI 로 resolve 시도
    (exit code 만 — 값 미캡처). backend CLI 미설치/미인증 → unknown(skip).
    """
    ref = reference_of(entry)
    if entry.backend not in KNOWN_BACKENDS:
        return SecretStatus(
            entry.name, entry.backend, ref, STATUS_UNKNOWN,
            f"미지의 backend — 지원: {', '.join(KNOWN_BACKENDS)}",
        )
    err = _handle_error(entry)
    if err:
        return SecretStatus(entry.name, entry.backend, ref, STATUS_INVALID, err)
    if not probe:
        return SecretStatus(entry.name, entry.backend, ref, STATUS_OK, "핸들 유효 (probe 생략)")
    status, detail = _PROBES[entry.backend](entry)
    return SecretStatus(entry.name, entry.backend, ref, status, detail)


def collect_secrets(
    *,
    cfg: object | None = None,
    config_path: Path | None = None,
    probe: bool = True,
    now: datetime | None = None,
) -> SecretsReport:
    """`secrets:` 레지스트리 entry 들을 verify 해 schema v1 report 로 반환.

    Args:
      cfg: 미리 로드된 AnvycConfig (테스트 주입). None 이면 config_path 로 로드.
      config_path: anvyc.yaml 경로 override.
      probe: True 면 backend CLI 로 resolvability 확인 (외부 호출). CI/offline 은 False.
      now: generated_at 기준 (테스트 주입).
    """
    if cfg is None:
        cfg = load_anvyc_config(config_path)
    n = now or datetime.now(tz=UTC)
    entries = [verify_entry(e, probe=probe) for e in cfg.secrets.entries]  # type: ignore[attr-defined]
    return SecretsReport(
        schema_version=SCHEMA_VERSION,
        generated_at=n.strftime("%Y-%m-%dT%H:%M:%SZ"),
        entries=entries,
    )
