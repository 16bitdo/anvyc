"""Cost adapters (CP-13 PR-13B1 + PR-13C + PR-13D).

Registry of source-specific adapters. anthropic (core dep), aws (optional
`cost-aws` — boto3), github (optional `cost-github` — httpx). Optional dep
부재 시 lazy import 가 entry 미등록 (graceful skip, ADR R11). 각 source 의
doctor check 가 부재 시 안내.
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
    """source 이름 → adapter 인스턴스. optional dep 부재 시 entry 제외.

    boto3 / httpx 가용성은 `importlib.util.find_spec` 로 가볍게 확인 (실
    import 0, startup 비용 무시 가능). 부재 시 해당 키 미등록 → doctor
    `cost-<src>-*` check 들이 안내.
    """
    import importlib.util  # noqa: PLC0415

    registry: dict[str, CostAdapter] = {
        "anthropic": AnthropicAdapter(),
    }
    if importlib.util.find_spec("boto3") is not None:
        from anvyc.core.cost.adapters.aws import (  # noqa: PLC0415
            AwsCostExplorerAdapter,
        )

        registry["aws"] = AwsCostExplorerAdapter()
    if importlib.util.find_spec("httpx") is not None:
        from anvyc.core.cost.adapters.github import (  # noqa: PLC0415
            GitHubBillingAdapter,
        )

        registry["github"] = GitHubBillingAdapter()
    return registry


ADAPTER_REGISTRY: dict[str, CostAdapter] = _build_registry()
