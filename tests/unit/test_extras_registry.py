"""ExtraReq SoT drift 가드 (PR1).

동반 도구(외부 CLI 바이너리 + Python extras) 레지스트리가 일관된 정적 메타를 노출하고,
헬퍼(is_available / install_hint / collect_extras_status)가 계약대로 동작하는지 강제한다.
분산 call site(sops.py / secrets.py / checks/*)와 `anvyc extras` 명령 / README 생성기가
모두 이 레지스트리를 단일 소스로 소비하므로, 여기서 drift 를 막는다.
"""

from __future__ import annotations

import pytest

from anvyc.core.extras import (
    EXTRA_KINDS,
    EXTRAS_REGISTRY,
    ExtraReq,
    collect_extras_status,
    find,
    install_hint,
    installed_version,
    is_available,
)

_ALL = list(EXTRAS_REGISTRY)


def test_registry_non_empty() -> None:
    assert _ALL, "EXTRAS_REGISTRY 비어 있음"


@pytest.mark.parametrize("req", _ALL, ids=lambda r: r.name)
def test_required_fields(req: ExtraReq) -> None:
    assert req.name.strip(), "name 비어있음"
    assert req.label.strip(), f"{req.name}: label 비어있음"
    assert req.purpose.strip(), f"{req.name}: purpose 비어있음"
    assert req.install_cmd.strip(), f"{req.name}: install_cmd 비어있음"
    assert req.kind in EXTRA_KINDS, f"{req.name}: kind 미허용값 {req.kind!r}"
    assert isinstance(req.probe, tuple) and req.probe, f"{req.name}: probe 비어있음"
    assert all(p.strip() for p in req.probe), f"{req.name}: probe 빈 항목"


@pytest.mark.parametrize("req", _ALL, ids=lambda r: r.name)
def test_kind_specific_invariants(req: ExtraReq) -> None:
    if req.kind == "pyextra":
        assert req.pip_extra, f"{req.name}: pyextra 는 pip_extra 필수"
        assert "pip install" in req.install_cmd, f"{req.name}: pyextra install_cmd 이상"
    else:  # binary
        assert req.pip_extra is None, f"{req.name}: binary 는 pip_extra 없어야 함"


def test_names_unique() -> None:
    names = [r.name for r in _ALL]
    assert len(names) == len(set(names)), "ExtraReq name 중복"


def test_platform_values_valid() -> None:
    for r in _ALL:
        assert r.platform in (None, "darwin"), f"{r.name}: platform 미허용값 {r.platform!r}"


def test_core_tools_present() -> None:
    """리팩터 call site 가 참조하는 핵심 도구가 레지스트리에 존재해야 한다."""
    names = {r.name for r in _ALL}
    for required in ("sops", "age", "op", "git", "gh", "pbcopy", "security"):
        assert required in names, f"{required} 누락"
    for extra in ("mcp", "textual", "boto3", "httpx", "cryptography"):
        assert extra in names, f"pyextra {extra} 누락"


def test_find_and_unknown() -> None:
    assert find("sops") is not None
    assert find("__nope__") is None
    assert is_available("__nope__") is False
    assert install_hint("__nope__") == ""
    assert installed_version("__nope__") is None


def test_install_hint_includes_url_when_present() -> None:
    sops = find("sops")
    assert sops is not None and sops.install_url
    hint = install_hint("sops")
    assert sops.install_cmd in hint and sops.install_url in hint


def test_binary_version_is_none() -> None:
    # binary 는 버전 추출 안 함 (도구별 상이) — 항상 None.
    assert installed_version("git") is None


def test_collect_status_shape() -> None:
    rows = collect_extras_status()
    assert len(rows) == len(_ALL)
    required_keys = {
        "name",
        "kind",
        "label",
        "purpose",
        "installed",
        "version",
        "install_cmd",
        "install_url",
        "pip_extra",
        "required",
        "platform",
        "relevant",
    }
    for row in rows:
        assert required_keys <= set(row), f"{row.get('name')}: 키 누락"
        assert isinstance(row["installed"], bool)
        assert isinstance(row["relevant"], bool)
