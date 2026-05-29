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

from anvyc.core.config import AnvycConfig, SecretEntry, load_anvyc_config

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
    cfg: AnvycConfig | None = None,
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
    entries = [verify_entry(e, probe=probe) for e in cfg.secrets.entries]
    return SecretsReport(
        schema_version=SCHEMA_VERSION,
        generated_at=n.strftime("%Y-%m-%dT%H:%M:%SZ"),
        entries=entries,
    )


# ===== Phase 2: add (write, 비-secret) + get (read, 게이팅) =====
#
# 불변식: anvyc 는 secret 값을 메모리/argv/temp 어디에도 보유하지 않는다.
# - add: 값 입력은 backend 네이티브 경로(op --generate / sops edit)에 위임.
#        backend 명령은 stdio 를 상속(capture 안 함)해 값이 anvyc 로 들어오지 않게 한다.
#        anvyc 는 결과 "핸들" 만 anvyc.yaml 에 등록한다.
# - get: resolve 명령의 stdout 을 sink(pbcopy/터미널)로 직접 흘리고 anvyc 는 미캡처.
# keychain / aws-vault add·get 은 Phase 2.5. 기존 값의 hidden-input 은 Phase 3(passthrough).

ADD_BACKENDS = (BACKEND_OP, BACKEND_SOPS, BACKEND_KEYCHAIN, BACKEND_AWS_VAULT)
_ADD_TIMEOUT_S = 300  # 대화형(op item create / $EDITOR / security / aws-vault) 사용자 대기 고려


class SecretAddError(ValueError):
    """secret add 입력/실행 오류."""


class SecretGetError(ValueError):
    """secret get 입력/실행 오류."""


@dataclass(frozen=True)
class AddPlan:
    """`secret add` dry-run plan. command 는 backend 네이티브 명령(값 미포함)."""

    name: str
    backend: str
    command: list[str]      # 빈 list = 실행할 backend 명령 없음(기존 reference 등록만)
    entry: SecretEntry      # anvyc.yaml 에 등록될 항목
    description: str
    warnings: list[str]


def plan_add(
    name: str,
    backend: str,
    *,
    generate: bool = False,
    ref: str | None = None,
    vault: str | None = None,
    title: str | None = None,
    file: str | None = None,
    key: str | None = None,
    service: str | None = None,
    account: str | None = None,
    profile: str | None = None,
) -> AddPlan:
    """backend 별 add plan 산출. **값을 받지 않는다** — 입력은 backend 네이티브 경로
    (op generate/ref · sops edit · security 대화형 프롬프트 · aws-vault add)에 위임.

    Raises:
      SecretAddError: 지원 밖 backend / 필수 옵션 누락.
    """
    if backend not in ADD_BACKENDS:
        raise SecretAddError(
            f"Phase 2 add 는 {' / '.join(ADD_BACKENDS)} 만 지원 (요청: {backend!r}). "
            "keychain / aws-vault 는 Phase 2.5, 기존 값 직접 입력은 Phase 3(passthrough)."
        )

    if backend == BACKEND_OP:
        if generate and ref:
            raise SecretAddError("op: --generate 와 --ref 는 동시 사용 불가")
        if generate:
            if not vault:
                raise SecretAddError("op --generate 는 --vault 필요 (op://<vault>/<title>/password)")
            t = title or name
            entry = SecretEntry(name=name, backend=BACKEND_OP, ref=f"op://{vault}/{t}/password")
            cmd = [
                "op", "item", "create",
                "--category=password", f"--title={t}", f"--vault={vault}",
                "--generate-password=letters,digits,symbols,32",
            ]
            return AddPlan(
                name, backend, cmd, entry,
                f"op item 생성(난수 password) → {entry.ref}",
                [
                    "op 이 password 를 생성·저장 — anvyc 는 값 미접촉.",
                    "생성 항목이 op 출력에 1회 표시될 수 있음(op 자체 UX).",
                ],
            )
        if ref:
            entry = SecretEntry(name=name, backend=BACKEND_OP, ref=ref)
            return AddPlan(
                name, backend, [], entry,
                f"기존 op reference 등록: {ref}",
                ["값 입력 없음 — 등록 후 `op read` 로 resolve 검증."],
            )
        raise SecretAddError("op backend 는 --generate (신규 생성) 또는 --ref (기존 등록) 중 하나 필요")

    if backend == BACKEND_SOPS:
        if not file:
            raise SecretAddError("sops backend 는 --file (SOPS 파일 경로) 필요")
        entry = SecretEntry(name=name, backend=BACKEND_SOPS, file=file, key=key)
        cmd = ["sops", "edit", str(Path(file).expanduser())]
        suffix = f"#{key}" if key else ""
        return AddPlan(
            name, backend, cmd, entry,
            f"sops edit {file} ($EDITOR 보호 버퍼) → sops:{file}{suffix} 등록",
            ["값 입력은 $EDITOR(sops tmpfs)에서 — anvyc 는 값 미접촉."],
        )

    if backend == BACKEND_KEYCHAIN:
        if not (service and account):
            raise SecretAddError("keychain backend 는 --service + --account 필요")
        entry = SecretEntry(name=name, backend=BACKEND_KEYCHAIN, service=service, account=account)
        # `-w` 를 마지막에 두면 security 가 hidden 프롬프트로 값을 받음 (anvyc 미접촉).
        # `-U` 로 기존 항목 업데이트 허용.
        cmd = ["security", "add-generic-password", "-U", "-s", service, "-a", account, "-w"]
        return AddPlan(
            name, backend, cmd, entry,
            f"security add-generic-password (hidden 프롬프트) → keychain:{service}/{account} 등록",
            ["값 입력은 security 의 hidden 프롬프트에서 — anvyc 는 값 미접촉.", "macOS 전용."],
        )

    # BACKEND_AWS_VAULT
    if not profile:
        raise SecretAddError("aws-vault backend 는 --profile 필요")
    entry = SecretEntry(name=name, backend=BACKEND_AWS_VAULT, profile=profile)
    cmd = ["aws-vault", "add", profile]
    return AddPlan(
        name, backend, cmd, entry,
        f"aws-vault add {profile} (access key 프롬프트) → aws-vault:{profile} 등록",
        [
            "access key id / secret 입력은 aws-vault 프롬프트에서 — anvyc 는 값 미접촉.",
            "조회는 단일 값이 아니라 `aws-vault exec` 주입 모델 — `secret get` 대신 inject-wire(Phase 2.5b) / exec 사용.",
        ],
    )


def _entry_to_dict(entry: SecretEntry) -> dict[str, object]:
    """SecretEntry → anvyc.yaml 직렬화 dict (None 핸들 필드 생략)."""
    out: dict[str, object] = {"name": entry.name, "backend": entry.backend}
    for fld in ("ref", "file", "key", "service", "account", "profile"):
        v = getattr(entry, fld)
        if v:
            out[fld] = v
    if entry.wire:
        out["wire"] = dict(entry.wire)
    return out


def execute_add(command: list[str], *, timeout: int = _ADD_TIMEOUT_S) -> int:
    """backend add 명령 실행. **stdio 상속**(capture 안 함) → 값이 anvyc 로 안 들어옴.

    command 가 빈 list 면 0 (실행할 것 없음 — 기존 reference 등록만).
    """
    if not command:
        return 0
    try:
        proc = subprocess.run(command, check=False, timeout=timeout)  # noqa: S603 — stdio 상속
    except FileNotFoundError as exc:
        raise SecretAddError(f"외부 명령 부재: {command[0]} — 설치 후 재시도.") from exc
    except subprocess.TimeoutExpired as exc:
        raise SecretAddError(f"add timeout (>{timeout}s): {command[0]}") from exc
    return proc.returncode


def register_entry(
    entry: SecretEntry,
    *,
    config_path: Path | None = None,
    make_backup: bool = True,
) -> Path:
    """entry 를 anvyc.yaml 의 secrets.entries 에 추가하고 파일을 다시 쓴다.

    write 전 sibling `.bak-<ts>` 로 local-backup (CP-4 안전 패턴). 중복 name 은 거부.
    anvyc.yaml 미발견 시 SecretAddError (anvyc init 먼저).
    """
    import shutil as _sh

    import yaml

    cfg = load_anvyc_config(config_path)
    target = getattr(cfg, "source", None)
    if target is None:
        raise SecretAddError("anvyc.yaml 을 찾을 수 없음 — `anvyc init` 먼저 또는 --config 지정")
    target = Path(target)

    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SecretAddError(f"anvyc.yaml 형식 오류: {target}")
    secrets = raw.setdefault("secrets", {})
    if not isinstance(secrets, dict):
        raise SecretAddError("anvyc.yaml 의 secrets: 가 매핑이 아님")
    entries = secrets.setdefault("entries", [])
    if not isinstance(entries, list):
        raise SecretAddError("anvyc.yaml 의 secrets.entries 가 list 가 아님")
    if any(isinstance(e, dict) and e.get("name") == entry.name for e in entries):
        raise SecretAddError(f"이미 등록된 name: {entry.name!r} (덮어쓰려면 먼저 제거)")

    entries.append(_entry_to_dict(entry))

    if make_backup:
        ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        _sh.copy2(target, target.with_name(f"{target.name}.bak-{ts}"))
    target.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return target


def get_entry_by_name(cfg: AnvycConfig, name: str) -> SecretEntry | None:
    """레지스트리에서 name 으로 entry 조회 (없으면 None)."""
    for e in cfg.secrets.entries:
        if e.name == name:
            return e
    return None


def resolve_command(entry: SecretEntry) -> list[str]:
    """get 용 backend resolve 명령. 값은 이 명령의 stdout 으로만 흐른다 (anvyc 미캡처).

    Raises:
      SecretGetError: Phase 2 미지원 backend (keychain/aws-vault → 2.5).
    """
    if entry.backend == BACKEND_OP:
        return ["op", "read", "--no-newline", entry.ref or ""]
    if entry.backend == BACKEND_SOPS:
        f = str(Path(entry.file or "").expanduser())
        if entry.key:
            return ["sops", "-d", "--extract", f'["{entry.key}"]', f]
        return ["sops", "-d", f]
    if entry.backend == BACKEND_KEYCHAIN:
        # -w → 값을 stdout 으로 (clipboard 파이프용). OS 가 keychain unlock 게이팅.
        return [
            "security", "find-generic-password", "-w",
            "-s", entry.service or "", "-a", entry.account or "",
        ]
    if entry.backend == BACKEND_AWS_VAULT:
        raise SecretGetError(
            "aws-vault 는 단일 값 get 모델이 아님 (exec 주입). "
            "`aws-vault exec <profile> -- <cmd>` 또는 inject-wire(Phase 2.5b) 사용."
        )
    raise SecretGetError(f"미지의 backend: {entry.backend!r}")
