from src.tools.material_tools import MaterialTool
from src.tools.script_tools import ScriptTool
from src.tools.cost_tools import CostTool
from src.models.schemas import StepStatus, TaskStep


def test_material_and_script_tools_are_structured():
    materials = MaterialTool()(topic="新品发布", variant="low_cost")
    assert materials.success and materials.data["material_cost"] == 5
    script = ScriptTool()(topic="新品发布", material_ids=[m["id"] for m in materials.data["materials"]], variant="low_cost")
    assert script.success and script.data["script_cost"] == 3


def test_cost_tool_checks_budget_and_deadline():
    result = CostTool()(material_cost=8, script_cost=4, material_duration=4, script_duration=2, budget=10, deadline="2020-01-01T00:00:00+00:00", now="2020-01-01T00:00:00+00:00")
    assert result.success
    assert result.data["total_cost"] == 12
    assert not result.data["meets_budget"]
    assert not result.data["meets_deadline"]
