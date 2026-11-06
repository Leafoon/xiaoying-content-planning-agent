from __future__ import annotations

from typing import Any

from ..models.schemas import ToolResult


class CostTool:
    name = "estimate_cost"

    def __call__(self, material_cost: float = 0.0, script_cost: float = 0.0, material_duration: float = 0.0, script_duration: float = 0.0, budget: float | None = None, deadline: str | None = None, now: str | None = None, **_: Any) -> ToolResult:
        total_cost = round(float(material_cost) + float(script_cost), 2)
        total_duration = round(float(material_duration) + float(script_duration), 2)
        remaining = round(float(budget) - total_cost, 2) if budget is not None else None
        meets_budget = budget is None or total_cost <= float(budget)
        meets_deadline = True
        deadline_gap_hours = 0.0
        if deadline:
            from datetime import datetime, timezone
            due = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            current = datetime.fromisoformat(now.replace("Z", "+00:00")) if now else datetime.now(timezone.utc)
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            available_hours = (due - current).total_seconds() / 3600
            deadline_gap_hours = round(available_hours - total_duration / 60, 2)
            meets_deadline = deadline_gap_hours >= 0
        return ToolResult(success=True, data={"total_cost": total_cost, "remaining_budget": remaining, "total_duration_minutes": total_duration, "meets_budget": meets_budget, "meets_deadline": meets_deadline, "deadline_gap_hours": deadline_gap_hours}, duration_seconds=0.01)
