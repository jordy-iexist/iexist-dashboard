"""AI-agents: herbruikbare agent-loop (base) + tools + per agent een submap.

Nieuwe agent toevoegen:
1. Map `app/agents/<naam>/` met `tools.py` (functies met @tool) en `agent.py`
   (een `build_<naam>_agent()` die een `Agent` teruggeeft).
2. Registreer hem hieronder in AGENTS.
3. Draai hem met `run_agent(build(), user_id=..., input=..., context=...)`.
"""
from typing import Callable

from app.agents.base import Agent, AgentRunResult, run_agent
from app.agents.nulmeting.agent import build_nulmeting_agent
from app.agents.tools import Tool, tool

AGENTS: dict[str, Callable[[], Agent]] = {
    "nulmeting": build_nulmeting_agent,
}

__all__ = ["AGENTS", "Agent", "AgentRunResult", "Tool", "run_agent", "tool"]
