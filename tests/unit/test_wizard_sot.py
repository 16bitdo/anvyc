"""wizard ↔ AdapterMeta SoT 정합 가드 (PR5).

init --interactive wizard 가 도구별 default 를 AdapterMeta 에서 가져오도록 리팩터된 뒤,
(1) prompt 순서가 ADAPTERS 전체를 덮는지, (2) 과거 중복 상수가 재도입되지 않았는지 강제.
"""
from __future__ import annotations

import anvyc.cli as cli_mod
from anvyc.cli import _WIZARD_TOOLS_ORDER
from anvyc.core.backup import ADAPTERS


def test_wizard_order_covers_all_adapters() -> None:
    """wizard prompt 순서가 ADAPTERS 전체를 정확히 덮어야 한다 (신규 adapter 누락 방지)."""
    assert set(_WIZARD_TOOLS_ORDER) == set(ADAPTERS)
    assert len(_WIZARD_TOOLS_ORDER) == len(ADAPTERS)  # 중복 없음


def test_wizard_legacy_default_constants_removed() -> None:
    """PR5: _WIZARD_* default 중복 상수는 제거되고 AdapterMeta SoT 로 대체됐다."""
    assert not hasattr(cli_mod, "_WIZARD_FILE_DEFAULTS")
    assert not hasattr(cli_mod, "_WIZARD_DEV_ENV_DEFAULTS")
