"""Tool-definitie voor agents: een Python-functie + JSON-schema."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

ToolFn = Callable[..., Any]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: ToolFn

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def run(self, context: Any, arguments: dict[str, Any]) -> Any:
        allowed = set((self.parameters.get("properties") or {}).keys())
        clean = {k: v for k, v in (arguments or {}).items() if k in allowed}
        return self.fn(context, **clean)


def tool(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> Callable[[ToolFn], Tool]:
    """Decorator: `@tool("naam", "uitleg", {...})` boven `def fn(ctx, **kwargs)`."""

    def decorator(fn: ToolFn) -> Tool:
        return Tool(
            name=name,
            description=description,
            parameters={
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
            fn=fn,
        )

    return decorator
