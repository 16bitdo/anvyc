"""AWS 계정 liveness probe — `aws sts get-caller-identity` (opt-in, 네트워크).

`anvyc aws profile --probe` 전용. doctor 는 이 모듈을 import 하지 않는다(offline 보장).
출력의 Account/Arn 은 식별자(로그에 흔함, 비밀 아님)라 표기 — 자격(키/토큰)은 미출력.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class ProbeResult:
    ok: bool
    account: str | None = None
    arn: str | None = None
    error: str | None = None


def probe_caller_identity(profile: str, *, timeout: float = 8.0) -> ProbeResult:
    """`aws sts get-caller-identity --profile X` 실행 결과. aws 부재/실패 시 graceful."""
    if shutil.which("aws") is None:
        return ProbeResult(ok=False, error="aws CLI 미설치 — probe 불가")
    try:
        proc = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--profile", profile, "--output", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(ok=False, error="timeout")
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        return ProbeResult(ok=False, error=(tail[-1][:200] if tail else "exit != 0"))
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return ProbeResult(ok=False, error="parse error")
    return ProbeResult(ok=True, account=data.get("Account"), arn=data.get("Arn"))
