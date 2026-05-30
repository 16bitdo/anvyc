"""anvyc 번들 pricing ↔ rbr SoT drift 가드 (CP-13 가격표 SoT 의 rbr 이전 정합).

pricing SoT 가 anvyc → rbr(`metadata/pricing/anthropic.yaml`)로 이전됨 (CP-14 후속,
SoT 일관성 = 모든 계약/참조 SoT 는 L1 rbr). anvyc 는 별도 패키지라 본 SoT 를 번들
복사해 cost 계산에 직접 사용하고, 본 가드가 drift 를 검출한다 (anvyx
tests/test_pricing_sync.py 와 대칭).

- `test_bundle_has_provenance_and_mirror_sections`: 항상 실행 (hermetic).
- `test_bundle_in_sync_with_rbr_sot`: SoT locatable 시 비교, 부재 시 skip.
  경로 override = `ANVYC_PRICING_SOT` env.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from anvyc.core.cost.pricing.loader import PRICING_FILE

_SOT_REL = "metadata/pricing/anthropic.yaml"
# .../anvyc/src/anvyc/core/cost/pricing/anthropic.yaml → parents[5] = .../anvyc (repo root)
_REPO_ROOT = PRICING_FILE.parents[5]
_SOT_CANDIDATES = (
    _REPO_ROOT.parent / "role-based-ruleset" / _SOT_REL,  # ../role-based-ruleset (sibling)
    Path("~/dev/role-based-ruleset").expanduser() / _SOT_REL,  # 표준 dev 레이아웃
)

_PROVENANCE_FIELDS = ("version", "effective_date", "source_url", "synced_from", "schema_version")
_MIRRORED = (
    "version",
    "effective_date",
    "models",
    "deprecated_models",
    "server_tools",
    "modifiers",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _find_sot() -> Path | None:
    env = os.environ.get("ANVYC_PRICING_SOT")
    if env:
        p = Path(env).expanduser()
        return p if p.is_file() else None
    for cand in _SOT_CANDIDATES:
        if cand.is_file():
            return cand
    return None


def test_bundle_has_provenance_and_mirror_sections() -> None:
    """번들이 동기화 추적용 provenance + 미러 섹션을 갖는다 (hermetic)."""
    data = _load_yaml(PRICING_FILE)
    for f in _PROVENANCE_FIELDS:
        assert f in data, f"번들 pricing provenance 필드 누락: {f}"
    assert isinstance(data.get("models"), dict) and data["models"], "models 섹션 비어있음"
    assert isinstance(data.get("deprecated_models"), dict), "deprecated_models 섹션 없음"


def test_bundle_in_sync_with_rbr_sot() -> None:
    """SoT 가 발견되면 번들이 그 version/effective_date/models/deprecated/server_tools/modifiers 와 일치."""
    sot_path = _find_sot()
    if sot_path is None:
        pytest.skip(
            "rbr SoT pricing 미발견 (CI/hermetic) — ANVYC_PRICING_SOT 로 경로 지정 가능."
        )
    bundle = _load_yaml(PRICING_FILE)
    sot = _load_yaml(sot_path)

    drift: list[str] = []
    for key in _MIRRORED:
        if bundle.get(key) != sot.get(key):
            drift.append(f"{key}: 번들={bundle.get(key)!r} ≠ SoT={sot.get(key)!r}")

    assert not drift, (
        "anvyc 번들 pricing 이 rbr SoT 와 drift 함 — "
        f"`{PRICING_FILE}` 의 version/effective_date/models/deprecated_models/server_tools/modifiers "
        f"+ synced_from 을 SoT(`{sot_path}`)에 맞춰 갱신하세요. 차이:\n  " + "\n  ".join(drift)
    )
