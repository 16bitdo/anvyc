"""examples/anvyc.yaml ↔ src/anvyc/templates.py:DEFAULT_ANVYC_YAML 의 drift lint.

두 SoT 는 의도가 분리됨 (drift sync PR #105 에서 명시):
- `templates.py:DEFAULT_ANVYC_YAML` — `anvyc init` 가 작성하는 minimal default.
  `include: []` 처럼 비워서 adapter defaults 사용 의도.
- `examples/anvyc.yaml` — 모든 옵션의 explicit reference. adapter default 값을
  명시해 사용자가 어떤 옵션이 있는지 한 파일에서 발견 가능.

따라서 string-level diff 는 의도적. 본 lint 는 두 SoT 가 **알아야 하는 도구
set 이 동일한지** 만 검증 — 신규 어댑터를 한쪽에만 추가하고 다른 쪽 누락
(PR #105 직전의 dev_env/shell_prompt 케이스) 을 재발 방지.

examples 에만 있는 opt-in section (예: `cost`) 은 정책상 허용 — templates
는 minimal 정책으로 부재. tools dict 의 top-level 키만 strict 일치 검증.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from anvyc.templates import DEFAULT_ANVYC_YAML

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLES_PATH = REPO_ROOT / "examples" / "anvyc.yaml"


def _load_examples() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(EXAMPLES_PATH.read_text()))


def _load_templates() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(DEFAULT_ANVYC_YAML))


def test_examples_yaml_parses() -> None:
    """examples/anvyc.yaml 이 yaml.safe_load 로 파싱 가능."""
    data = _load_examples()
    assert isinstance(data, dict)
    assert data.get("version") == 1


def test_templates_yaml_parses() -> None:
    """templates.DEFAULT_ANVYC_YAML 이 yaml.safe_load 로 파싱 가능."""
    data = _load_templates()
    assert isinstance(data, dict)
    assert data.get("version") == 1


def test_tools_keys_identical() -> None:
    """두 SoT 의 `tools.<key>` set 이 정확히 일치.

    drift 재발 방지 — 신규 어댑터를 한쪽에만 추가하는 실수를 lint 에서 차단.
    """
    ex_tools = set(_load_examples()["tools"].keys())
    tp_tools = set(_load_templates()["tools"].keys())

    examples_only = ex_tools - tp_tools
    templates_only = tp_tools - ex_tools

    assert not examples_only and not templates_only, (
        "examples/anvyc.yaml ↔ templates.py 의 tools key drift — "
        f"examples 만: {sorted(examples_only)} / templates 만: {sorted(templates_only)}. "
        "한쪽에 도구 추가 시 다른 쪽도 sync 필요."
    )


def test_doctor_cross_user_present_in_both() -> None:
    """doctor.cross_user section 이 두 SoT 모두에 존재 — 기본 check 의 일관성."""
    ex_doctor = _load_examples().get("doctor", {})
    tp_doctor = _load_templates().get("doctor", {})
    assert "cross_user" in ex_doctor
    assert "cross_user" in tp_doctor


def test_top_level_keys_examples_superset_of_templates() -> None:
    """examples 의 top-level keys 는 templates 의 superset.

    templates 는 minimal — opt-in section (예: `cost`) 은 examples 에만 있을 수 있음.
    반대로 templates 에만 있는 top-level key 는 examples 누락이라 drift.
    """
    ex_keys = set(_load_examples().keys())
    tp_keys = set(_load_templates().keys())

    templates_only = tp_keys - ex_keys
    assert not templates_only, (
        f"templates.py 에만 있는 top-level key (examples 누락): {sorted(templates_only)}. "
        "examples 가 explicit reference 이므로 templates 의 모든 top-level section 을 포함해야 함."
    )
