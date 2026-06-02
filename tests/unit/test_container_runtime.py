"""Unit tests for container-runtime-health check."""
from __future__ import annotations

from unittest.mock import patch

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.container_runtime import ContainerRuntimeHealthCheck

_MOD = "anvyc.checks.container_runtime"


def test_silent_when_colima_absent() -> None:
    """colima 미설치 머신 → silent(N/A)."""
    with patch(f"{_MOD}._colima_installed", return_value=False):
        res = ContainerRuntimeHealthCheck().run(CheckContext())
    assert res == []


def test_running_but_docker_dead_warns() -> None:
    """colima Running + docker 미응답 → WARNING(2차 손상)."""
    with patch(f"{_MOD}._colima_installed", return_value=True), \
         patch(f"{_MOD}.colima_vm_status", return_value="Running"), \
         patch(f"{_MOD}.docker_reachable", return_value=False):
        res = ContainerRuntimeHealthCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "docker" in res[0].message
    assert res[0].suggestion is not None and "recreate" in res[0].suggestion


def test_running_and_docker_ok_silent() -> None:
    """정상(Running + docker OK) → silent(손상 아님)."""
    with patch(f"{_MOD}._colima_installed", return_value=True), \
         patch(f"{_MOD}.colima_vm_status", return_value="Running"), \
         patch(f"{_MOD}.docker_reachable", return_value=True):
        res = ContainerRuntimeHealthCheck().run(CheckContext())
    assert res == []


def test_stopped_with_stale_lock_warns() -> None:
    """colima Stopped + stale 디스크 잠금 → WARNING(1차)."""
    with patch(f"{_MOD}._colima_installed", return_value=True), \
         patch(f"{_MOD}.colima_vm_status", return_value="Stopped"), \
         patch(f"{_MOD}.colima_stale_lock", return_value=True):
        res = ContainerRuntimeHealthCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "잠금" in res[0].message


def test_stopped_clean_silent() -> None:
    """clean stopped(락 없음) → silent."""
    with patch(f"{_MOD}._colima_installed", return_value=True), \
         patch(f"{_MOD}.colima_vm_status", return_value="Stopped"), \
         patch(f"{_MOD}.colima_stale_lock", return_value=False):
        res = ContainerRuntimeHealthCheck().run(CheckContext())
    assert res == []


def test_no_instance_silent() -> None:
    """limactl 이 인스턴스 부재/오류('') 반환 → silent."""
    with patch(f"{_MOD}._colima_installed", return_value=True), \
         patch(f"{_MOD}.colima_vm_status", return_value=""):
        res = ContainerRuntimeHealthCheck().run(CheckContext())
    assert res == []
