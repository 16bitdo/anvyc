"""Cost adapters (CP-13 PR-13B1).

Registry of source-specific adapters. 본 PR-13B1 에서 anthropic 만 등록,
AWS / GitHub 는 PR-13C / PR-13D 에서 추가.
"""

from anvyc.core.cost.adapters.anthropic import AnthropicAdapter
from anvyc.core.cost.adapters.base import CostAdapter, CostAdapterDepMissingError

__all__ = [
    "ADAPTER_REGISTRY",
    "AnthropicAdapter",
    "CostAdapter",
    "CostAdapterDepMissingError",
]


def _build_registry() -> dict[str, CostAdapter]:
    """source 이름 → adapter 인스턴스. PR-13C/D 진입 시 entry 추가."""
    return {
        "anthropic": AnthropicAdapter(),
    }


ADAPTER_REGISTRY: dict[str, CostAdapter] = _build_registry()
