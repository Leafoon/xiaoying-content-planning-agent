from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from src.agent.core import AgentRunner
from src.config import Settings
from src.models.schemas import PlanningRequest

@pytest.fixture
def request_factory():
    def make(task_id="task", budget=20, deadline_hours=1, preferences=None, **kwargs):
        topic = kwargs.pop("topic", "新品发布")
        return PlanningRequest(task_id=task_id, topic=topic, budget=budget, deadline=datetime.now(timezone.utc) + timedelta(hours=deadline_hours) if deadline_hours is not None else None, preferences=preferences or {}, **kwargs)
    return make

@pytest.fixture
def runner(tmp_path):
    return AgentRunner(settings=Settings(database_path=tmp_path / "test.db"))
