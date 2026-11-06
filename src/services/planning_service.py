from __future__ import annotations

from typing import Any
from ..agent.core import AgentRunner
from ..config import Settings
from ..models.schemas import AgentResult, PlanningRequest
from ..repositories.database import Database


class PlanningService:
    """Application facade for callers that do not need to know the agent internals."""
    def __init__(self, db: Database | None = None, settings: Settings | None = None, model_client: Any | None = None) -> None:
        self.runner = AgentRunner(db=db, settings=settings, model_client=model_client)

    def plan(self, request: PlanningRequest | dict[str, Any]) -> AgentResult:
        return self.runner.run(request)
