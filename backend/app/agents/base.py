"""Herbruikbare agent-loop op de OpenAI Responses API met function calling.

Een agent = instructies + een set tools. `run_agent` laat het model tools
aanroepen tot het een eindantwoord geeft of `max_steps` bereikt is. Tools
krijgen een `context` mee (bv. db-sessie + scan_id) en kunnen dus alleen bij
de data die de aanroeper toestaat.

Met `output_schema` geeft de agent zijn eindantwoord als JSON volgens dat
schema (structured output); `AgentRunResult.parsed()` levert dan de dict.
`input` mag ook een lijst content-onderdelen zijn (tekst + afbeeldingen).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.tools import Tool
from app.services.openai.client import _build_openai_client, model_supports_reasoning

logger = logging.getLogger(__name__)

MAX_TOOL_OUTPUT_CHARS = 12_000
TRACE_PREVIEW_CHARS = 600


@dataclass
class Agent:
    name: str
    instructions: str
    tools: list[Tool]
    model: str
    max_steps: int = 8
    max_output_tokens: int = 6000
    reasoning_effort: str | None = "low"
    # JSON-schema voor het eindantwoord (strict: alle velden verplicht,
    # additionalProperties false). None = vrije tekst.
    output_schema: dict[str, Any] | None = None


@dataclass
class AgentRunResult:
    output: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    stopped_reason: str = "completed"

    def parsed(self) -> dict[str, Any]:
        """Eindantwoord als dict (voor agents met `output_schema`)."""
        try:
            data = json.loads(self.output or "")
        except ValueError as exc:
            raise ValueError(f"Agent gaf geen geldig JSON-antwoord ({self.stopped_reason}).") from exc
        if not isinstance(data, dict):
            raise ValueError("Agent gaf geen JSON-object terug.")
        return data

    def to_trace(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "steps": self.steps,
            "usage": {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens},
            "stopped_reason": self.stopped_reason,
        }


def _serialize(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > MAX_TOOL_OUTPUT_CHARS:
        text = text[:MAX_TOOL_OUTPUT_CHARS] + "…(ingekort)"
    return text


def text_part(text: str) -> dict[str, Any]:
    return {"type": "input_text", "text": text}


def image_part(url: str, detail: str = "low") -> dict[str, Any]:
    return {"type": "input_image", "image_url": url, "detail": detail}


def run_agent(
    agent: Agent, *, user_id: str, input: str | list[dict[str, Any]], context: Any
) -> AgentRunResult:
    client = _build_openai_client(user_id)
    tools_by_name = {t.name: t for t in agent.tools}
    result = AgentRunResult(output="", model=agent.model)
    items: list[Any] = [{"role": "user", "content": input}]

    for step in range(agent.max_steps):
        last_step = step == agent.max_steps - 1
        payload: dict[str, Any] = {
            "model": agent.model,
            "instructions": agent.instructions,
            "input": items,
            "max_output_tokens": agent.max_output_tokens,
        }
        if agent.tools:
            payload["tools"] = [t.schema() for t in agent.tools]
            # Laatste stap: geen tools meer, dwing een eindantwoord af.
            payload["tool_choice"] = "none" if last_step else "auto"
        if agent.reasoning_effort and model_supports_reasoning(agent.model):
            payload["reasoning"] = {"effort": agent.reasoning_effort}
        if agent.output_schema is not None:
            payload["text"] = {"format": {
                "type": "json_schema",
                "name": f"{agent.name}_output",
                "schema": agent.output_schema,
                "strict": True,
            }}

        response = client.responses.create(**payload)
        usage = getattr(response, "usage", None)
        if usage is not None:
            result.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
            result.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)

        calls = [item for item in response.output if getattr(item, "type", "") == "function_call"]
        if not calls:
            result.output = (response.output_text or "").strip()
            result.stopped_reason = "completed"
            return result

        # Model-output (incl. reasoning-items) terug in de context zetten.
        items.extend(response.output)
        for call in calls:
            tool = tools_by_name.get(call.name)
            try:
                arguments = json.loads(call.arguments or "{}")
            except ValueError:
                arguments = {}
            if tool is None:
                output: Any = {"error": f"Onbekende tool: {call.name}"}
            else:
                try:
                    output = tool.run(context, arguments)
                except Exception as exc:  # tool-fout terug naar het model
                    logger.warning("Agent %s tool %s faalde: %s", agent.name, call.name, exc)
                    output = {"error": str(exc)}
            serialized = _serialize(output)
            items.append({"type": "function_call_output", "call_id": call.call_id, "output": serialized})
            result.steps.append({
                "step": step + 1,
                "tool": call.name,
                "arguments": arguments,
                "output_preview": serialized[:TRACE_PREVIEW_CHARS],
            })

    result.stopped_reason = "max_steps"
    return result
