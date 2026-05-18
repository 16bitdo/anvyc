"""SOPS subprocess wrapper — age backend.

DESIGN.md §31. sops binary 가 모든 cryptographic 작업을 담당하며 anvyc 는
얇은 wrapper 만 제공.

함수:
  - encrypt(src, dst, recipients)             age 공개 키로 암호화
  - decrypt(src, dst, identity_file=None)     age 개인 키로 복호화
  - is_sops_encrypted(path)                    SOPS metadata 가 있는지 확인
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_TIMEOUT_S = 30
SOPS_BIN = "sops"
SOPS_MARKER_BYTES = b'"sops":'
SOPS_YAML_MARKER = b"sops:"


class SopsError(RuntimeError):
    pass


def sops_available() -> bool:
    return shutil.which(SOPS_BIN) is not None


def encrypt(src: Path, dst: Path, recipients: list[str]) -> None:
    """src 를 age recipients 로 암호화해 dst 에 저장.

    PoC 는 항상 binary 모드 — byte-for-byte 보존 보장.
    .yaml/.json 의 in-place 부분 암호화는 v0.2.1+ 옵션으로 검토.
    """
    if not sops_available():
        raise SopsError("sops binary 미설치 (brew install sops)")
    if not recipients:
        raise SopsError("age_recipients 비어 있음 (anvyc.yaml security.sops.age_recipients)")
    if not src.is_file():
        raise SopsError(f"source 파일 없음: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    args = [
        SOPS_BIN,
        "--encrypt",
        "--age",
        ",".join(recipients),
        "--input-type", "binary",
        "--output-type", "json",   # SOPS metadata 가 들어가 .sops.json 으로 저장
        "--output",
        str(dst),
        str(src),
    ]
    result = subprocess.run(args, capture_output=True, text=True, timeout=_TIMEOUT_S)
    if result.returncode != 0:
        raise SopsError(f"sops encrypt 실패 (exit {result.returncode}): {result.stderr.strip()}")


def decrypt(src: Path, dst: Path, identity_file: Path | None = None) -> None:
    """src(SOPS) 를 복호화해 dst 에 원본 평문 저장.

    binary 모드로 암호화된 파일을 byte-for-byte 복원.
    identity_file 미지정 시 sops 가 환경변수 (SOPS_AGE_KEY_FILE 또는 default
    ~/.config/sops/age/keys.txt) 를 자동 사용한다.
    """
    if not sops_available():
        raise SopsError("sops binary 미설치 (brew install sops)")
    if not src.is_file():
        raise SopsError(f"source 파일 없음: {src}")

    env = os.environ.copy()
    if identity_file is not None:
        env["SOPS_AGE_KEY_FILE"] = str(identity_file)

    dst.parent.mkdir(parents=True, exist_ok=True)
    args = [
        SOPS_BIN,
        "--decrypt",
        "--input-type", "json",      # 우리가 .sops.json 으로 저장했음
        "--output-type", "binary",   # 원본 형식 (binary) 으로 복원
        "--output",
        str(dst),
        str(src),
    ]
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=_TIMEOUT_S, env=env
    )
    if result.returncode != 0:
        raise SopsError(f"sops decrypt 실패 (exit {result.returncode}): {result.stderr.strip()}")


def is_sops_encrypted(path: Path) -> bool:
    """파일명 또는 내용 첫 4KB 로 SOPS metadata 존재 여부 추정."""
    try:
        # 파일명 힌트
        name = path.name.lower()
        if ".sops." in name or name.endswith(".enc") or name.endswith(".sops"):
            # 파일명만으로는 false positive 가능 — 내용으로도 확인
            pass
        if not path.is_file():
            return False
        if path.stat().st_size > 10_000_000:
            return False
        with path.open("rb") as f:
            head = f.read(4096)
        return SOPS_MARKER_BYTES in head or SOPS_YAML_MARKER in head
    except (OSError, PermissionError):
        return False


def _guess_input_type(src: Path) -> str:
    """sops --input-type 값 결정. 모르면 binary."""
    s = src.suffix.lower()
    if s in (".yaml", ".yml"):
        return "yaml"
    if s == ".json":
        return "json"
    if s == ".env":
        return "dotenv"
    if s == ".ini":
        return "ini"
    return "binary"
