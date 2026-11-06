from pathlib import Path
from datetime import datetime, timedelta, timezone
from src.repositories.database import Database
from src.models.schemas import PlanningRequest, AgentMode, TaskStep, StepStatus, TraceEvent
from src.agent.core import AgentRunner
from src.config import Settings
from concurrent.futures import ThreadPoolExecutor


def test_sqlite_persists_steps_and_trace(tmp_path):
    path = tmp_path / "persist.db"
    db = Database(path); db.initialize()
    req = PlanningRequest(task_id="persist", topic="主题", budget=1, deadline=datetime.now(timezone.utc)+timedelta(hours=1))
    db.create_or_get_task(req, AgentMode.MOCK)
    step = TaskStep(step_id="s1", step_name="search", tool_name="search_materials", status=StepStatus.SUCCESS, result={"ok": True})
    db.upsert_step("persist", step)
    db.add_trace(TraceEvent(task_id="persist", step="1", action="tool_call", tool_name="search_materials"))
    db.close()
    db2 = Database(path); db2.initialize()
    assert db2.get_steps("persist")[0].status is StepStatus.SUCCESS
    assert db2.get_traces("persist")[0]["tool_name"] == "search_materials"


def test_concurrent_save_is_atomic(tmp_path):
    db = Database(tmp_path / "concurrent.db")
    db.initialize()
    req = PlanningRequest(task_id="concurrent", topic="主题", budget=10, deadline=datetime.now(timezone.utc)+timedelta(hours=1))
    db.create_or_get_task(req, AgentMode.MOCK)
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda i: db.save_proposal("concurrent", {"attempt": i})[0], range(8)))
    assert len(set(ids)) == 1
    assert db.count_proposals("concurrent") == 1


def test_stale_running_step_is_recovered(tmp_path):
    path = tmp_path / "resume.db"
    db = Database(path); db.initialize()
    deadline = datetime.now(timezone.utc) + timedelta(hours=1)
    req = PlanningRequest(task_id="stale", topic="新品发布", budget=20, deadline=deadline)
    db.create_or_get_task(req, AgentMode.MOCK)
    db.upsert_step("stale", TaskStep(step_id="search_materials_1", step_name="search_materials", tool_name="search_materials", status=StepStatus.RUNNING))
    result = AgentRunner(settings=Settings(database_path=path)).run(req)
    assert result.status.value == "COMPLETED"
    assert any(step.error and "中断" in step.error for step in result.steps)
