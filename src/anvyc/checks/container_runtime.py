"""container-runtime-health check.

colima(vz) 기반 docker 런타임의 *손상* 상태를 관측한다(직접 관리 안 함 — observability).
colima 미설치 머신(CI/headless/Linux/Docker Desktop)은 silent(N/A). 정상·clean-stopped·
인스턴스 부재도 silent. **손상 2종만 WARNING**:
- colima VM Running 인데 docker 미응답 → 게스트 손상 의심(recreate 필요). (2차 케이스)
- colima VM Stopped 인데 디스크 stale 잠금(IN-USE-BY) → 다음 start 실패 예고(colima-guard). (1차 케이스)

VM 상태는 `colima status`(손상 시 rc!=0 라 부정확) 대신 `limactl`(권위)로 판정.
모든 외부 호출은 bounded timeout + fail-safe. RCA 2026-06-02 colima 사가 — 무증상
docker-down 을 statusline ⚠️ 로 조기 포착하기 위함.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from anvyc.checks.base import CheckContext, CheckResult, Severity

COLIMA_BIN = "colima"
LIMACTL_BIN = "limactl"
DOCKER_BIN = "docker"
_TIMEOUT = 10.0
_LIMA_HOME = os.path.expanduser("~/.colima/_lima")


def _colima_installed() -> bool:
    return shutil.which(COLIMA_BIN) is not None


def _run(args: list[str], *, env: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=_TIMEOUT, env=env
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, proc.stdout


def colima_vm_status() -> str:
    """lima 인스턴스 상태(Running/Stopped/...) 또는 ''(부재/오류). limactl 이 권위."""
    env = {**os.environ, "LIMA_HOME": _LIMA_HOME}
    rc, out = _run([LIMACTL_BIN, "list", "--format", "{{.Status}}", "colima"], env=env)
    return out.strip() if rc == 0 else ""


def docker_reachable() -> bool:
    rc, _ = _run([DOCKER_BIN, "ps"])
    return rc == 0


def colima_stale_lock() -> bool:
    """colima 디스크가 IN-USE-BY(잠김)인지 — Stopped 인데 잠김 = stale 락."""
    env = {**os.environ, "LIMA_HOME": _LIMA_HOME}
    rc, out = _run([LIMACTL_BIN, "disk", "list"], env=env)
    if rc != 0:
        return False
    for line in out.splitlines()[1:]:  # header skip
        fields = line.split()
        # NAME SIZE FORMAT DIR IN-USE-BY → 잠김이면 5필드(IN-USE-BY 채워짐)
        if len(fields) >= 5 and fields[0] == "colima":
            return True
    return False


class ContainerRuntimeHealthCheck:
    name = "container-runtime-health"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        if not _colima_installed():
            return []  # colima 미사용 머신 → silent (N/A)
        status = colima_vm_status()
        if status == "Running" and not docker_reachable():
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message="colima VM 은 Running 이나 docker 미응답 — 게스트 손상 의심",
                    suggestion=(
                        "recreate: colima stop && colima delete --force && colima start"
                    ),
                )
            ]
        if status == "Stopped" and colima_stale_lock():
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message="colima 정지 상태인데 디스크 stale 잠금 — 다음 start 실패 가능",
                    suggestion="colima-guard 실행 또는 limactl disk unlock colima",
                )
            ]
        return []  # 정상 running+docker / clean stopped / 인스턴스 부재 → silent
