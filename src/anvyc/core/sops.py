"""SOPS subprocess wrapper — age backend.

DESIGN.md §31. sops binary 가 모든 cryptographic 작업을 담당하며 anvyc 는
얇은 wrapper 만 제공.

지원 모드 (v0.3.0):
  - "binary" (기본): 모든 파일을 binary 로 처리, output 은 .sops.json. byte-for-byte 보존.
  - "inplace": yaml/json/dotenv/ini 의 값만 SOPS 로 암호화 (키는 평문 유지).
               sops 본래 기능 활용. metadata 에 "sops/age/inplace" 로 표시.

함수:
  - encrypt(src, dst, recipients, mode)              age 공개 키로 암호화
  - decrypt(src, dst, identity_file=None, mode)      age 개인 키로 복호화
  - is_sops_encrypted(path)                           SOPS metadata 가 있는지 확인
  - guess_inplace_type(path)                          inplace 모드 input/output type
"""
from __future__ import annotations

import contextlib
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


def guess_inplace_type(path: Path) -> str:
    """inplace 모드용 input-type 추론. 모르면 'binary' 폴백."""
    s = path.suffix.lower()
    if s in (".yaml", ".yml"):
        return "yaml"
    if s == ".json":
        return "json"
    if s == ".env":
        return "dotenv"
    if s == ".ini":
        return "ini"
    return "binary"


def encrypt(
    src: Path, dst: Path, recipients: list[str], mode: str = "binary"
) -> None:
    """src 를 age recipients 로 암호화해 dst 에 저장.

    mode="binary": byte-for-byte 보존, 출력 형식 json.
    mode="inplace": yaml/json/dotenv/ini 의 값만 암호화, 키와 형식은 유지.
                    인식 불가능한 확장자는 자동으로 binary 폴백.
    """
    if not sops_available():
        raise SopsError("sops binary 미설치 (brew install sops)")
    if not recipients:
        raise SopsError("age_recipients 비어 있음 (anvyc.yaml security.sops.age_recipients)")
    if not src.is_file():
        raise SopsError(f"source 파일 없음: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "inplace":
        itype = guess_inplace_type(src)
        # 확장자 인식 실패(binary) → json, 그 외는 itype 그대로
        otype = "json" if itype == "binary" else itype
    else:  # binary
        itype = "binary"
        otype = "json"

    args = [
        SOPS_BIN,
        "--encrypt",
        "--age",
        ",".join(recipients),
        "--input-type", itype,
        "--output-type", otype,
        "--output",
        str(dst),
        str(src),
    ]
    result = subprocess.run(args, capture_output=True, text=True, timeout=_TIMEOUT_S)
    if result.returncode != 0:
        raise SopsError(f"sops encrypt 실패 (exit {result.returncode}): {result.stderr.strip()}")


def decrypt(
    src: Path,
    dst: Path,
    identity_file: Path | None = None,
    mode: str = "binary",
) -> None:
    """src(SOPS) 를 복호화해 dst 에 원본 평문 저장.

    mode 는 encrypt 때와 같아야 한다 (metadata 의 encryption 필드에서 결정).
    inplace 모드는 src 의 확장자로 input-type 자동 추론.
    """
    if not sops_available():
        raise SopsError("sops binary 미설치 (brew install sops)")
    if not src.is_file():
        raise SopsError(f"source 파일 없음: {src}")

    env = os.environ.copy()
    if identity_file is not None:
        env["SOPS_AGE_KEY_FILE"] = str(identity_file)

    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "inplace":
        type_ = guess_inplace_type(src)
        if type_ == "binary":
            # 인식 실패 → binary 폴백
            itype = "json"
            otype = "binary"
        else:
            itype = type_
            otype = type_
    else:  # binary
        itype = "json"
        otype = "binary"

    args = [
        SOPS_BIN,
        "--decrypt",
        "--input-type", itype,
        "--output-type", otype,
        "--output",
        str(dst),
        str(src),
    ]
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=_TIMEOUT_S, env=env
    )
    if result.returncode != 0:
        raise SopsError(f"sops decrypt 실패 (exit {result.returncode}): {result.stderr.strip()}")


def rotate_recipients(
    file: Path,
    new_recipients: list[str],
    identity_file: Path | None = None,
    mode: str = "binary",
) -> None:
    """SOPS 파일의 recipient 를 new_recipients 로 교체. atomic.

    동작:
      1. tempfile 에 decrypt
      2. tempfile → new_recipients 로 encrypt (목적지: 원본 파일 옆 .new 임시)
      3. 성공 시 os.replace 로 원본 swap
      4. tempfile (평문) 즉시 삭제

    실패 시 원본은 그대로 보존되며 SopsError raise.
    """
    import os
    import tempfile

    if not file.is_file():
        raise SopsError(f"파일 없음: {file}")
    if not new_recipients:
        raise SopsError("new_recipients 비어 있음")

    # 1) decrypt → temp plain
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        plain_tmp = Path(tf.name)
    new_enc_tmp = file.parent / f".{file.name}.rotate-new"
    try:
        decrypt(file, plain_tmp, identity_file=identity_file, mode=mode)
        # 2) encrypt → new temp
        encrypt(plain_tmp, new_enc_tmp, new_recipients, mode=mode)
        # 3) atomic replace
        os.replace(new_enc_tmp, file)
    finally:
        # 4) 평문 tempfile 즉시 삭제 (성공/실패 무관)
        for p in (plain_tmp, new_enc_tmp):
            with contextlib.suppress(OSError):
                p.unlink()


def is_sops_encrypted(path: Path) -> bool:
    """파일명 또는 내용 첫 4KB 로 SOPS metadata 존재 여부 추정."""
    try:
        name = path.name.lower()
        if ".sops." in name:
            return True
        if not path.is_file():
            return False
        if path.stat().st_size > 10_000_000:
            return False
        with path.open("rb") as f:
            head = f.read(4096)
        return SOPS_MARKER_BYTES in head or SOPS_YAML_MARKER in head
    except (OSError, PermissionError):
        return False
