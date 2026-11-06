from __future__ import annotations
from typing import Any

class BudgetService:
    @staticmethod
    def check(total_cost: float, budget: float | None) -> dict[str, Any]:
        return {"meets_budget": budget is None or total_cost <= budget, "remaining_budget": None if budget is None else round(budget - total_cost, 2)}
