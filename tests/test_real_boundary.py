import pytest
import time
from datetime import datetime, timedelta, timezone
from src.agent.core import AgentRunner
from src.config import Settings
from src.models.schemas import PlanningRequest, ToolResult, TaskStatus, Decision
from src.tools.registry import ToolRegistry
from src.agent.model_client import RealModelClient

def test_real_mode_requires_key():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        RealModelClient(None)


def test_tool_timeout_is_recorded_without_waiting_for_tool(tmp_path):
    registry = ToolRegistry()
    def slow_tool(**kwargs):
        time.sleep(0.3)
        return ToolResult(success=True, data={})
    registry.register("search_materials", slow_tool)
    start = time.perf_counter()
    runner = AgentRunner(settings=Settings(database_path=tmp_path / "timeout.db", tool_timeout_seconds=0.02), registry=registry)
    result = runner.run(PlanningRequest(task_id="timeout", topic="新品发布", budget=10, deadline=datetime.now(timezone.utc) + timedelta(hours=1)))
    assert result.status is TaskStatus.INCOMPLETE
    assert any("超时" in (step.error or "") for step in result.steps)
    assert time.perf_counter() - start < 0.2


def test_real_like_client_uses_same_engine_and_trace_mode(tmp_path):
    class RealLikeClient:
        mode = "real"

        def decide(self, state, tools):
            last_tool = state.get("last_tool")
            last = state.get("last_result") or {}
            req = state["request"]
            if last_tool is None:
                return Decision(action="tool_call", tool_name="search_materials", arguments={"topic": req["topic"], "variant": "low_cost", "preferences": {}})
            if last_tool == "search_materials":
                return Decision(action="tool_call", tool_name="generate_script", arguments={"topic": req["topic"], "material_ids": [m["id"] for m in last["data"]["materials"]], "variant": "low_cost", "preferences": {}})
            if last_tool == "generate_script":
                material = state["material_result"]["data"]
                script = last["data"]
                return Decision(action="tool_call", tool_name="estimate_cost", arguments={"material_cost": material["material_cost"], "script_cost": script["script_cost"], "material_duration": material["material_duration"], "script_duration": script["script_duration"], "budget": req["budget"], "deadline": req["deadline"], "now": state["now"]})
            if last_tool == "estimate_cost":
                return Decision(action="tool_call", tool_name="save_proposal", arguments={"task_id": req["task_id"], "proposal": state["proposal"]})
            return Decision(action="finish", final_status=TaskStatus.COMPLETED, message="saved")

    request = PlanningRequest(task_id="real-like", topic="新品发布", budget=20, deadline=datetime.now(timezone.utc) + timedelta(hours=1))
    result = AgentRunner(settings=Settings(database_path=tmp_path / "real-like.db"), model_client=RealLikeClient()).run(request)
    assert result.status is TaskStatus.COMPLETED
    assert result.proposal_id
    assert result.traces and all(trace["mode"] == "real" for trace in result.traces)


def test_engine_rejects_model_attempt_to_save_over_budget(tmp_path):
    class LiarClient:
        mode = "real"

        def decide(self, state, tools):
            last = state.get("last_tool")
            req = state["request"]
            if last is None:
                return Decision(action="tool_call", tool_name="search_materials", arguments={"topic": req["topic"], "variant": "standard"})
            if last == "search_materials":
                return Decision(action="tool_call", tool_name="generate_script", arguments={"topic": req["topic"], "material_ids": state["material_ids"], "variant": "standard"})
            if last == "generate_script":
                return Decision(action="tool_call", tool_name="estimate_cost", arguments={"material_cost": 0, "script_cost": 0, "material_duration": 0, "script_duration": 0, "budget": 1, "deadline": req["deadline"], "now": state["now"]})
            if last == "estimate_cost":
                return Decision(action="tool_call", tool_name="save_proposal", arguments={"task_id": req["task_id"], "proposal": {}})
            return Decision(action="finish", final_status=TaskStatus.COMPLETED)

    request = PlanningRequest(task_id="liar", topic="新品发布", budget=1, deadline=datetime.now(timezone.utc) + timedelta(hours=1))
    result = AgentRunner(settings=Settings(database_path=tmp_path / "liar.db"), model_client=LiarClient()).run(request)
    assert result.status is TaskStatus.INCOMPLETE
    assert result.proposal_id is None
    assert any("禁止保存" in (step.error or "") for step in result.steps)
