"""AdapterMeta SoT drift 가드 (PR1).

10개 adapter 가 일관된 정적 메타데이터를 노출하는지, 그리고 표시용 메타가 실제
adapter 동작(DEFAULT_FILES / exclude())과 어긋나지 않는지 강제한다. tools list /
configure / wizard / MCP / README 가 모두 이 메타를 단일 소스로 소비하므로, 여기서
drift 를 막는 것이 전체 UX 의 정합성 전제다.

참고: 새 adapter 를 ADAPTERS 에 등록하면서 meta 를 빠뜨리면 mypy 가 먼저
(Adapter Protocol 불만족으로) 잡는다. 본 테스트는 mypy 를 돌리지 않는 환경을 위한
런타임 belt-and-suspenders + 표시/실동작 정합 검증이다.
"""
from __future__ import annotations

import pytest

from anvyc.adapters import aws, gh, git, pulumi, shell, shell_prompt
from anvyc.adapters.base import ADAPTER_CATEGORIES, Adapter, AdapterMeta
from anvyc.core.backup import ADAPTERS

# exclude() 가 사용자-facing 경로/relpath 문자열을 반환해, meta.excludes 의 부분집합
# 여부를 HOME 비의존적으로 검증할 수 있는 adapter 들. (cursor 는 절대경로·HOME 의존,
# iterm2 는 plist 키 → 부분집합 검증에서 제외하고 비어있지 않음만 확인한다.)
_SUBSET_CHECK = ("shell", "git", "aws", "gh", "pulumi", "claude", "dev_env")

# file-based adapter — meta.includes 가 모듈 DEFAULT_FILES 와 *동일* 이어야 한다.
_FILE_BASED = (
    (shell.ShellAdapter, shell.DEFAULT_FILES),
    (git.GitAdapter, git.DEFAULT_FILES),
    (aws.AwsAdapter, aws.DEFAULT_FILES),
    (gh.GhAdapter, gh.DEFAULT_FILES),
    (pulumi.PulumiAdapter, pulumi.DEFAULT_FILES),
    (shell_prompt.ShellPromptAdapter, shell_prompt.DEFAULT_FILES),
)

_ALL = list(ADAPTERS.items())


@pytest.mark.parametrize("name,cls", _ALL)
def test_every_adapter_exposes_meta(name: str, cls: type[Adapter]) -> None:
    assert isinstance(getattr(cls, "meta", None), AdapterMeta), f"{name}: meta 부재"


@pytest.mark.parametrize("name,cls", _ALL)
def test_meta_name_matches_registry_and_class(name: str, cls: type[Adapter]) -> None:
    adapter = cls()
    assert adapter.meta.name == name, f"{name}: meta.name 이 registry key 와 불일치"
    assert adapter.meta.name == adapter.name, f"{name}: meta.name 이 .name 과 불일치"


@pytest.mark.parametrize("name,cls", _ALL)
def test_meta_required_fields(name: str, cls: type[Adapter]) -> None:
    meta = cls().meta
    assert meta.label.strip(), f"{name}: label 비어있음"
    assert meta.summary.strip(), f"{name}: summary 비어있음"
    assert meta.since.strip(), f"{name}: since 비어있음"
    assert meta.category in ADAPTER_CATEGORIES, f"{name}: category 미허용값 {meta.category!r}"
    assert meta.config_kind in {"files", "structured"}, f"{name}: config_kind 미허용값"
    assert isinstance(meta.includes, tuple) and meta.includes, f"{name}: includes 비어있음"
    assert isinstance(meta.excludes, tuple), f"{name}: excludes 가 tuple 아님"


def test_default_enabled_policy() -> None:
    """dev_env 만 default 비활성(안전), 그 외 활성 — wizard 리팩터(PR5) drift 가드."""
    for name, cls in ADAPTERS.items():
        expected = name != "dev_env"
        assert cls().meta.default_enabled is expected, name


def test_no_unused_categories() -> None:
    """선언된 category 허용값에 미사용(오타) 항목이 없는지 — 집합 위생."""
    used = {cls().meta.category for cls in ADAPTERS.values()}
    unused = ADAPTER_CATEGORIES - used
    assert not unused, f"미사용 category 허용값 (오타 의심): {sorted(unused)}"


@pytest.mark.parametrize("cls,default_files", _FILE_BASED)
def test_file_based_includes_match_default_files(
    cls: type[Adapter], default_files: tuple[str, ...]
) -> None:
    assert cls.meta.includes == default_files


@pytest.mark.parametrize("name", _SUBSET_CHECK)
def test_displayed_excludes_are_real(name: str) -> None:
    """표시용 meta.excludes 의 각 항목이 실제 exclude() 에 존재해야 한다 (거짓 표시 방지)."""
    adapter = ADAPTERS[name]()
    real = set(adapter.exclude())  # default 생성 — fs 접근 없이 정적 목록 반환
    missing = set(adapter.meta.excludes) - real
    assert not missing, f"{name}: meta.excludes 가 실제 제외에 없음 {sorted(missing)}"


@pytest.mark.parametrize("name", ("cursor", "iterm2"))
def test_structured_with_excludes_show_something(name: str) -> None:
    """부분집합 검증에서 빠진 구조형 adapter 도, 실제 제외가 있으면 표시도 비어있지 않아야."""
    adapter = ADAPTERS[name]()
    if adapter.exclude():
        assert adapter.meta.excludes, f"{name}: 제외가 있는데 표시용 excludes 비어있음"
