"""Multi-agent adapter registry (CP-7, Control Plane v4).

본 package 는 AI agent (Claude Code / Cursor / Codex / ...) 별 observability
어댑터를 dispatch 한다. 추가 agent 는 `<name>.py` 모듈 + `register_agent()`
1줄로 등록한다 (DESIGN.md §7.7 참조).

SoT 분담:
- agent 메타 (display_name, hook 지원 등): role-based-ruleset/templates/agents/_schema.yaml
- agent dispatch (본 모듈): AGENT_REGISTRY
- agent 자산 (hook 본문 등): role-based-ruleset/templates/agents/<agent>/
"""

# Side-effect imports: 각 어댑터 모듈은 import 시 register_agent() 호출.
from anvyc.agents import claude_code as _claude_code  # noqa: F401
from anvyc.agents import codex as _codex  # noqa: F401
from anvyc.agents import cursor as _cursor  # noqa: F401
from anvyc.agents.base import (
    AGENT_REGISTRY,
    UNIFIED_SCHEMA_VERSION,
    AgentAdapter,
    get_agent,
    list_agents,
    register_agent,
)

__all__ = [
    "AGENT_REGISTRY",
    "AgentAdapter",
    "UNIFIED_SCHEMA_VERSION",
    "get_agent",
    "list_agents",
    "register_agent",
]
