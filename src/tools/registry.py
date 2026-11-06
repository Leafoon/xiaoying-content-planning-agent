from __future__ import annotations

from typing import Any, Callable

from ..models.schemas import ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., ToolResult]] = {}

    def register(self, name: str, tool: Callable[..., ToolResult]) -> None:
        self._tools[name] = tool

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if name not in self._tools:
            return ToolResult(success=False, error=f"未知工具: {name}", retryable=False)
        return self._tools[name](**arguments)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        parameter_schemas: dict[str, dict[str, Any]] = {
            "search_materials": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "preferences": {"type": "object"},
                    "variant": {"type": "string", "enum": ["standard", "high_cost", "low_cost", "fast"]},
                },
                "required": ["topic", "variant"],
                "additionalProperties": True,
            },
            "generate_script": {
                "type": "object",
                "properties": {"topic": {"type": "string"}, "material_ids": {"type": "array", "items": {"type": "string"}}, "variant": {"type": "string"}, "preferences": {"type": "object"}},
                "required": ["topic", "material_ids", "variant"],
                "additionalProperties": True,
            },
            "estimate_cost": {
                "type": "object",
                "properties": {"material_cost": {"type": "number"}, "script_cost": {"type": "number"}, "material_duration": {"type": "number"}, "script_duration": {"type": "number"}, "budget": {"type": ["number", "null"]}, "deadline": {"type": ["string", "null"]}, "now": {"type": ["string", "null"]}},
                "required": ["material_cost", "script_cost", "material_duration", "script_duration", "budget", "deadline", "now"],
                "additionalProperties": True,
            },
            "save_proposal": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}, "proposal": {"type": "object"}},
                "required": ["task_id", "proposal"],
                "additionalProperties": True,
            },
        }
        return [{"type": "function", "function": {"name": n, "description": f"内容规划工具 {n}", "parameters": parameter_schemas.get(n, {"type": "object", "additionalProperties": True})}} for n in self._tools]
