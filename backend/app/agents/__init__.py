"""AI-agents: herbruikbare agent-loop (base) + tools + per agent een submap.

Nieuwe agent toevoegen:
1. Map `app/agents/<naam>/` met `tools.py` (functies met @tool) en `agent.py`
   (een `build_<naam>_agent()` die een `Agent` teruggeeft).
2. Registreer hem hieronder in AGENTS.
3. Draai hem met `run_agent(build(), user_id=..., input=..., context=...)`.
"""
from typing import Callable

from app.agents.base import Agent, AgentRunResult, run_agent
from app.agents.content_gap.agent import build_content_gap_agent
from app.agents.content_links.agent import build_content_links_agent
from app.agents.content_meta.agent import build_content_meta_agent
from app.agents.content_report.agent import build_content_report_agent
from app.agents.content_text.agent import build_content_text_agent
from app.agents.content_trust.agent import build_content_trust_agent
from app.agents.geo.agent import build_geo_agent
from app.agents.nulmeting.agent import build_nulmeting_agent
from app.agents.quarterly_report.agent import build_quarterly_report_agent
from app.agents.tools import Tool, tool

AGENTS: dict[str, Callable[[], Agent]] = {
    "nulmeting": build_nulmeting_agent,
    "geo": build_geo_agent,
    # Fase 3 (content & onpage): vier pagina-agents, contentgap en rapport.
    "content_meta": build_content_meta_agent,
    "content_text": build_content_text_agent,
    "content_trust": build_content_trust_agent,
    "content_links": build_content_links_agent,
    "content_gap": build_content_gap_agent,
    "content_report": build_content_report_agent,
    # Fase 4 (kwartaal GEO-werkzaamheden): conceptrapport.
    "quarterly_report": build_quarterly_report_agent,
}

__all__ = ["AGENTS", "Agent", "AgentRunResult", "Tool", "run_agent", "tool"]
