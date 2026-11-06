from src.models.schemas import TaskStatus, StepStatus


def test_normal_completion(runner, request_factory):
    result = runner.run(request_factory("normal"))
    assert result.status is TaskStatus.COMPLETED
    assert result.proposal_id
    assert result.total_cost == 14
    assert all(step.status is StepStatus.SUCCESS for step in result.steps)
    assert all(step.estimated_duration > 0 for step in result.steps)
    assert [step.estimated_cost for step in result.steps] == [11, 3, 14, 0]
    proposal = runner.db.get_proposal("normal")[1]
    assert proposal["budget"] == 20
    assert proposal["deadline"]
    assert any(t["action"] == "model_decision" for t in result.traces)


def test_missing_budget_or_deadline_is_needs_info(runner, request_factory):
    missing_budget = runner.run(request_factory("missing-budget", budget=None))
    assert missing_budget.status is TaskStatus.NEEDS_INFO
    assert "budget" in missing_budget.missing_fields
    assert missing_budget.steps == []
    missing_deadline = runner.run(request_factory("missing-deadline", deadline_hours=None))
    assert missing_deadline.status is TaskStatus.NEEDS_INFO
    assert "deadline" in missing_deadline.missing_fields


def test_missing_info_task_can_be_completed_later(runner, request_factory):
    incomplete_request = request_factory("fill-info", budget=None)
    first = runner.run(incomplete_request)
    completed = runner.run(incomplete_request.model_copy(update={"budget": 20}))
    assert first.status is TaskStatus.NEEDS_INFO
    assert completed.status is TaskStatus.COMPLETED


def test_same_task_id_with_different_business_request_is_rejected(runner, request_factory):
    first = runner.run(request_factory("conflict", topic="新品发布"))
    second = runner.run(request_factory("conflict", topic="校园活动"))
    assert first.status is TaskStatus.COMPLETED
    assert second.status is TaskStatus.FAILED
    assert "请求内容不一致" in second.message
    assert second.proposal_id == first.proposal_id


def test_failure_replans_and_keeps_failed_step(runner, request_factory):
    result = runner.run(request_factory("failure", preferences={"fail_material_once": True}))
    assert result.status is TaskStatus.COMPLETED
    assert any(s.status is StepStatus.FAILED for s in result.steps)
    assert any(s.status is StepStatus.SUCCESS for s in result.steps)
    assert any(t.get("replanning_reason") for t in result.traces if t["action"] == "tool_call")


def test_script_failure_can_switch_generation_variant(runner, request_factory):
    result = runner.run(request_factory("script-failure", preferences={"fail_script_once": True}))
    assert result.status is TaskStatus.COMPLETED
    script_steps = [step for step in result.steps if step.tool_name == "generate_script"]
    assert script_steps[0].status is StepStatus.FAILED
    assert script_steps[1].status is StepStatus.SUCCESS
    assert script_steps[1].result["variant"] == "fast"


def test_partial_material_result_is_preserved_in_trace(runner, request_factory):
    result = runner.run(request_factory("partial", preferences={"partial_material": True}))
    assert result.status is TaskStatus.COMPLETED
    assert any(trace["result_summary"].get("partial") for trace in result.traces if trace["tool_name"] == "search_materials")


def test_budget_overrun_switches_to_low_cost(runner, request_factory):
    result = runner.run(request_factory("budget", budget=10, preferences={"variant": "high_cost"}))
    assert result.status is TaskStatus.COMPLETED
    assert result.total_cost == 8
    assert result.proposal_id
    assert [s.actual_cost for s in result.steps if s.tool_name == "estimate_cost"] == [12, 8]


def test_all_alternatives_over_budget_is_incomplete(runner, request_factory):
    result = runner.run(request_factory("all-over", budget=1, preferences={"variant": "high_cost"}))
    assert result.status is TaskStatus.INCOMPLETE
    assert result.proposal_id is None
    assert result.total_cost == 8
    assert result.constraint_details["remaining_budget"] == -7
    assert "预算缺口" in result.message


def test_idempotent_repeat_does_not_create_second_proposal(runner, request_factory):
    request = request_factory("repeat")
    first = runner.run(request)
    second = runner.run(request)
    assert first.status is TaskStatus.COMPLETED
    assert second.status is TaskStatus.COMPLETED
    assert second.proposal_id == first.proposal_id
    assert runner.db.count_proposals("repeat") == 1
    assert len(second.steps) == len(first.steps)


def test_deadline_replans_to_fast_then_stops_if_still_impossible(runner, request_factory):
    result = runner.run(request_factory("deadline", deadline_hours=0.0001, preferences={"variant": "high_cost"}))
    assert result.status is TaskStatus.INCOMPLETE
    assert any(s.result and s.result.get("variant") == "fast" for s in result.steps if s.tool_name == "search_materials")


def test_max_steps_is_explicit(runner, request_factory):
    runner.settings = runner.settings.__class__(**{**runner.settings.__dict__, "max_agent_steps": 2})
    result = runner.run(request_factory("limited"))
    assert result.status is TaskStatus.INCOMPLETE
    assert "最大决策轮数" in result.message or "最大工具" in result.message


def test_max_tool_calls_is_explicit(runner, request_factory):
    runner.settings = runner.settings.__class__(**{**runner.settings.__dict__, "max_tool_calls": 1})
    result = runner.run(request_factory("tool-limit"))
    assert result.status is TaskStatus.INCOMPLETE
    assert "最大工具调用次数" in result.message


def test_failed_save_can_resume_without_repeating_successful_work(runner, request_factory):
    request = request_factory("resume-save", preferences={"force_save_failure": True})
    failed = runner.run(request)
    assert failed.status is TaskStatus.FAILED
    resumed = runner.run(request.model_copy(update={"preferences": {}}))
    assert resumed.status is TaskStatus.COMPLETED
    assert [s.tool_name for s in resumed.steps].count("generate_script") == 1
    assert [s.tool_name for s in resumed.steps].count("estimate_cost") == 1


def test_continuous_failure_stops_with_explicit_incomplete(runner, request_factory):
    result = runner.run(request_factory("continuous-failure", preferences={"force_material_failure": True}))
    assert result.status is TaskStatus.INCOMPLETE
    assert result.message
