from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..models.schemas import AgentMode, AgentResult, Decision, PlanningRequest, StepStatus, TaskStatus, TaskStep, ToolResult, TraceEvent
from ..mock.mock_model import MockModelClient
from ..repositories.database import Database
from ..tools.cost_tools import CostTool
from ..tools.material_tools import MaterialTool
from ..tools.proposal_tools import ProposalTool
from ..tools.registry import ToolRegistry
from ..tools.script_tools import ScriptTool
from .model_client import RealModelClient


class AgentRunner:
    """Shared multi-turn execution engine for Mock and Real model clients."""

    def __init__(self, db: Database | None = None, settings: Settings | None = None, model_client: Any | None = None, registry: ToolRegistry | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.db = db or Database(self.settings.database_path)
        self.db.initialize()
        self.registry = registry or ToolRegistry()
        # A supplied registry may override one tool for failure/timeout tests,
        # while the remaining production tools are still available.
        registered = set(self.registry.names())
        if "search_materials" not in registered: self.registry.register("search_materials", MaterialTool())
        if "generate_script" not in registered: self.registry.register("generate_script", ScriptTool())
        if "estimate_cost" not in registered: self.registry.register("estimate_cost", CostTool())
        if "save_proposal" not in registered: self.registry.register("save_proposal", ProposalTool(self.db.save_proposal))
        if model_client is not None:
            self.model = model_client
        elif self.settings.agent_mode == AgentMode.REAL:
            self.model = RealModelClient(self.settings.openai_api_key, self.settings.openai_model, self.settings.openai_base_url)
        else:
            self.model = MockModelClient()

    def run(self, request: PlanningRequest | dict[str, Any]) -> AgentResult:
        if not isinstance(request, PlanningRequest):
            request = PlanningRequest.model_validate(request)
        model_mode = getattr(self.model, "mode", "mock")
        mode = AgentMode.REAL if model_mode in {"real", AgentMode.REAL} else AgentMode.MOCK
        task_row = self.db.create_or_get_task(request, mode)
        if task_row is not None and not self.db.request_matches(task_row, request) and not (
            task_row["status"] == TaskStatus.NEEDS_INFO.value and self.db.request_fills_missing_info(task_row, request)
        ):
            # A task id is an idempotency key. Reusing it for another business
            # request would mix steps and proposals from unrelated work.
            message = "task_id 已存在，但请求内容不一致"
            self.db.update_task(request.task_id, TaskStatus.FAILED, message)
            self._trace(request.task_id, "validation", {}, "final", None, {}, {"error": message}, "PLANNING->FAILED", "stop", 0, mode, message)
            return self._result(request, TaskStatus.FAILED, message)
        missing = [field for field in ("budget", "deadline") if getattr(request, field) is None]
        if missing:
            message = f"缺少必要输入: {', '.join(missing)}"
            self.db.update_task(request.task_id, TaskStatus.NEEDS_INFO, message)
            self._trace(request.task_id, "validation", {}, "final", None, {}, {}, "PLANNING->NEEDS_INFO", "stop", 0, mode, message)
            return self._result(request, TaskStatus.NEEDS_INFO, message, missing)

        existing = self.db.get_task(request.task_id)
        if existing and existing["status"] == TaskStatus.NEEDS_INFO.value:
            # Filling previously missing required information is a supported
            # continuation, while changing a concrete request is rejected above.
            self.db.update_task_request(request.task_id, request)
        existing_proposal = self.db.get_proposal(request.task_id)
        if existing and existing["status"] == TaskStatus.COMPLETED.value and existing_proposal:
            return self._result(request, TaskStatus.COMPLETED, "已复用已保存方案", [], existing_proposal[0])

        steps = self.db.get_steps(request.task_id)
        # A process may have died after marking a step RUNNING. Turn that stale
        # state into an auditable failure before resuming the task.
        for stale in steps:
            if stale.status == StepStatus.RUNNING:
                stale.status = StepStatus.FAILED
                stale.error = "上次执行中断，已转为可恢复失败"
                self.db.upsert_step(request.task_id, stale)
                self._trace(request.task_id, "recovery", {"stale_step": stale.step_id}, "recovery", stale.tool_name, {}, {"error": stale.error}, "RUNNING->FAILED", "resume", 0, mode, replanning_reason="检测到上次执行遗留的 RUNNING 步骤")
        steps = self.db.get_steps(request.task_id)
        state = self._initial_state(request, steps)
        self.db.update_task(request.task_id, TaskStatus.RUNNING, "开始执行动态规划")
        tool_calls = 0
        last_tool: str | None = state.get("last_tool")
        last_result: ToolResult | None = ToolResult.model_validate(state["last_result"]) if state.get("last_result") else None
        last_reason = ""

        for turn in range(1, self.settings.max_agent_steps + 1):
            state["last_tool"] = last_tool
            state["last_result"] = last_result.model_dump(mode="json") if last_result else None
            state["tool_history"] = state.get("tool_history", [])
            state["now"] = datetime.now(timezone.utc).isoformat()
            try:
                decision = self.model.decide(state, self.registry.schemas())
            except Exception as exc:
                message = f"模型决策失败: {exc}"
                self.db.update_task(request.task_id, TaskStatus.FAILED, message)
                self._trace(request.task_id, str(turn), state, "model_error", None, {}, {"error": str(exc)}, "RUNNING->FAILED", "stop", 0, mode, message)
                return self._result(request, TaskStatus.FAILED, message)
            self._trace(request.task_id, str(turn), state, "model_decision", decision.tool_name, decision.arguments, {"action": decision.action, "tool_name": decision.tool_name, "reason": decision.reason}, "", decision.tool_name or decision.action, 0, mode)
            last_reason = decision.reason

            if decision.action in {"finish", "final", "stop"}:
                status = decision.final_status or TaskStatus.INCOMPLETE
                if status == TaskStatus.COMPLETED and not self.db.get_proposal(request.task_id):
                    status = TaskStatus.INCOMPLETE
                message = decision.message or ("任务完成" if status == TaskStatus.COMPLETED else "任务未完成")
                self.db.update_task(request.task_id, status, message)
                self._trace(request.task_id, str(turn), state, "final", None, {}, {"message": message}, f"RUNNING->{status.value}", "stop", 0, mode, status.value)
                proposal_id = self.db.get_proposal(request.task_id)
                return self._result(request, status, message, [], proposal_id[0] if proposal_id else None)

            if decision.action != "tool_call" or not decision.tool_name:
                message = "模型未返回可执行动作"
                self.db.update_task(request.task_id, TaskStatus.FAILED, message)
                return self._result(request, TaskStatus.FAILED, message)
            if tool_calls >= self.settings.max_tool_calls:
                message = f"达到最大工具调用次数 {self.settings.max_tool_calls}"
                self.db.update_task(request.task_id, TaskStatus.INCOMPLETE, message)
                self._trace(request.task_id, str(turn), state, "limit", None, {}, {"error": message}, "RUNNING->INCOMPLETE", "stop", 0, mode, message)
                return self._result(request, TaskStatus.INCOMPLETE, message)

            tool_calls += 1
            tool_name = decision.tool_name
            args = dict(decision.arguments)
            args, validation_error = self._normalize_tool_arguments(tool_name, args, state, request)
            step = self._make_step(request.task_id, tool_name, args, self.db.get_steps(request.task_id))
            if validation_error:
                result = ToolResult(success=False, error=validation_error, retryable=False)
                step.status = StepStatus.FAILED
                step.error = validation_error
                self.db.record_tool_execution(request.task_id, step, args, result.model_dump(mode="json"))
                last_tool, last_result = tool_name, result
                state["tool_history"].append({"tool": tool_name, "success": False, "error": result.error})
                self._trace(request.task_id, str(turn), state, "tool_call", tool_name, args, {"error": result.error}, "PENDING->FAILED", "replan", 0, mode, replanning_reason="引擎约束校验失败")
                continue
            if not self._dependencies_met(step, self.db.get_steps(request.task_id)):
                result = ToolResult(success=False, error="步骤依赖尚未完成", retryable=False)
                step.status = StepStatus.FAILED
                step.error = result.error
                self.db.record_tool_execution(request.task_id, step, args, result.model_dump(mode="json"))
                last_tool, last_result = tool_name, result
                state["tool_history"].append({"tool": tool_name, "success": False, "error": result.error})
                self._trace(request.task_id, str(turn), state, "tool_call", tool_name, args, {"error": result.error}, "PENDING->FAILED", "replan", 0, mode, replanning_reason="依赖校验失败")
                continue

            step.status = StepStatus.RUNNING
            self.db.upsert_step(request.task_id, step)
            start = datetime.now(timezone.utc)
            result = self._execute_with_timeout(tool_name, args)
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            result.duration_seconds = elapsed
            step.status = StepStatus.SUCCESS if result.success else StepStatus.FAILED
            step.result = result.data
            step.error = result.error
            step.actual_cost = self._actual_cost(tool_name, result)
            step.estimated_duration = self._duration_from_result(tool_name, result, step.estimated_duration)
            self.db.record_tool_execution(request.task_id, step, args, result.model_dump(mode="json"))
            state["tool_history"].append({"tool": tool_name, "success": result.success, "error": result.error, "data": result.data})
            self._update_state(state, tool_name, args, result)
            last_tool, last_result = tool_name, result
            status_change = f"RUNNING->{step.status.value}"
            self.db.update_task(request.task_id, TaskStatus.REPLANNING if not result.success or tool_name == "estimate_cost" else TaskStatus.RUNNING, result.error or "观察工具结果并重新规划")
            self._trace(request.task_id, str(turn), state, "tool_call", tool_name, args, self._summary(result), status_change, "replan", elapsed, mode, replanning_reason=last_reason if not result.success else None)

        message = f"达到最大决策轮数 {self.settings.max_agent_steps}，任务未完成"
        self.db.update_task(request.task_id, TaskStatus.INCOMPLETE, message)
        self._trace(request.task_id, "limit", state, "final", None, {}, {"error": message}, "RUNNING->INCOMPLETE", "stop", 0, mode, message)
        return self._result(request, TaskStatus.INCOMPLETE, message)

    def _execute_with_timeout(self, name: str, args: dict[str, Any]) -> ToolResult:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self.registry.call, name, args)
        try:
            return future.result(timeout=self.settings.tool_timeout_seconds)
        except FutureTimeout:
            future.cancel()
            return ToolResult(success=False, error=f"工具 {name} 超时", retryable=True)
        except Exception as exc:
            return ToolResult(success=False, error=f"工具 {name} 异常: {exc}", retryable=False)
        finally:
            # Do not wait for a misbehaving tool after the configured timeout.
            pool.shutdown(wait=False, cancel_futures=True)

    def _initial_state(self, request: PlanningRequest, steps: list[TaskStep]) -> dict[str, Any]:
        state: dict[str, Any] = {"request": request.model_dump(mode="json"), "variant": request.preferences.get("variant", "standard"), "attempts": {}, "tool_history": [], "now": datetime.now(timezone.utc).isoformat()}
        for step in steps:
            if step.status != StepStatus.SUCCESS or not step.result:
                continue
            state["tool_history"].append({"tool": step.tool_name, "success": True, "data": step.result})
            self._update_state(state, step.tool_name, {}, ToolResult(success=True, data=step.result))
            state["last_tool"] = step.tool_name
            state["last_result"] = ToolResult(success=True, data=step.result).model_dump(mode="json")
        return state

    def _update_state(self, state: dict[str, Any], tool_name: str, args: dict[str, Any], result: ToolResult) -> None:
        state.setdefault("attempts", {})[tool_name] = state.setdefault("attempts", {}).get(tool_name, 0) + 1
        if not result.success:
            return
        if tool_name == "search_materials":
            state["material_result"] = result.model_dump(mode="json")
            state["material_ids"] = [m["id"] for m in result.data.get("materials", [])]
            state["variant"] = args.get("variant", result.data.get("variant", state.get("variant", "standard")))
            # A new material search invalidates downstream script and estimate
            # observations from the previous branch.
            state.pop("script_result", None)
            state.pop("estimate_result", None)
            state.pop("proposal", None)
        elif tool_name == "generate_script":
            state["script_result"] = result.model_dump(mode="json")
            state["variant"] = result.data.get("variant", state.get("variant", "standard"))
            state.pop("estimate_result", None)
            state["proposal"] = {"task_id": state["request"]["task_id"], "topic": state["request"]["topic"], "budget": state["request"].get("budget"), "deadline": state["request"].get("deadline"), "variant": state.get("variant"), "materials": state.get("material_result", {}).get("data", {}).get("materials", []), "script": result.data}
        elif tool_name == "estimate_cost":
            state["estimate_result"] = result.model_dump(mode="json")
            state.setdefault("proposal", {})["estimate"] = result.data

    def _make_step(self, task_id: str, tool_name: str, args: dict[str, Any], existing: list[TaskStep]) -> TaskStep:
        same = [s for s in existing if s.tool_name == tool_name]
        number = len(same) + 1
        step_id = f"{tool_name}_{number}"
        deps: list[str] = []
        if tool_name == "generate_script":
            deps = [next((s.step_id for s in reversed(existing) if s.tool_name == "search_materials" and s.status == StepStatus.SUCCESS), "")]
        elif tool_name == "estimate_cost":
            deps = [s.step_id for s in existing if s.tool_name in {"search_materials", "generate_script"} and s.status == StepStatus.SUCCESS][-2:]
        elif tool_name == "save_proposal":
            deps = [next((s.step_id for s in reversed(existing) if s.tool_name == "estimate_cost" and s.status == StepStatus.SUCCESS), "")]
        deps = [d for d in deps if d]
        variant = str(args.get("variant", "standard"))
        if tool_name == "estimate_cost":
            estimated_cost = float(args.get("material_cost", 0) or 0) + float(args.get("script_cost", 0) or 0)
        else:
            estimated_cost = float(args.get("script_cost", 0) or args.get("material_cost", 0) or {
                "search_materials": {"high_cost": 8.0, "standard": 11.0, "low_cost": 5.0, "fast": 3.0},
                "generate_script": {"high_cost": 4.0, "standard": 3.0, "low_cost": 3.0, "fast": 2.0},
            }.get(tool_name, {}).get(variant, 0.0))
        estimated_duration = {
            "search_materials": {"high_cost": 4.0, "standard": 4.0, "low_cost": 2.0, "fast": 1.0}.get(str(args.get("variant", "standard")), 4.0),
            "generate_script": {"high_cost": 2.0, "standard": 1.5, "low_cost": 1.5, "fast": 0.5}.get(str(args.get("variant", "standard")), 1.5),
            "estimate_cost": 0.1,
            "save_proposal": 0.1,
        }.get(tool_name, 0.0)
        return TaskStep(step_id=step_id, step_name=tool_name, description=f"执行 {tool_name}", dependencies=deps, tool_name=tool_name, estimated_cost=estimated_cost, estimated_duration=estimated_duration)

    def _normalize_tool_arguments(self, tool_name: str, args: dict[str, Any], state: dict[str, Any], request: PlanningRequest) -> tuple[dict[str, Any], str | None]:
        """Keep model-selected actions dynamic while preventing constraint bypasses."""
        normalized = dict(args)
        if tool_name == "search_materials":
            normalized["topic"] = request.topic
            variant = str(normalized.get("variant", state.get("variant", "standard")))
            if variant not in {"standard", "high_cost", "low_cost", "fast"}:
                return normalized, f"不支持的素材方案: {variant}"
            normalized["variant"] = variant
            normalized["preferences"] = dict(request.preferences)
        elif tool_name == "generate_script":
            material_ids = list(state.get("material_ids", []))
            requested_ids = list(normalized.get("material_ids", material_ids))
            if requested_ids != material_ids:
                return normalized, "脚本素材必须来自最近一次成功检索"
            requested_variant = str(normalized.get("variant", state.get("variant", "standard")))
            if requested_variant not in {"standard", "high_cost", "low_cost", "fast"}:
                return normalized, f"不支持的脚本方案: {requested_variant}"
            normalized.update({"topic": request.topic, "material_ids": material_ids, "variant": requested_variant, "preferences": dict(request.preferences)})
        elif tool_name == "estimate_cost":
            material = state.get("material_result", {}).get("data", {})
            script = state.get("script_result", {}).get("data", {})
            if not material or not script:
                return normalized, "估算前缺少成功的素材或脚本结果"
            normalized.update({"material_cost": material.get("material_cost", 0), "script_cost": script.get("script_cost", 0), "material_duration": material.get("material_duration", 0), "script_duration": script.get("script_duration", 0), "budget": request.budget, "deadline": request.deadline.isoformat() if request.deadline else None, "now": state.get("now")})
        elif tool_name == "save_proposal":
            estimate = state.get("estimate_result", {}).get("data", {})
            if not estimate:
                return normalized, "保存前缺少成功的成本估算"
            if not estimate.get("meets_budget") or not estimate.get("meets_deadline"):
                return normalized, "预算或截止时间不满足，禁止保存方案"
            normalized["task_id"] = request.task_id
            normalized["proposal"] = state.get("proposal", normalized.get("proposal", {}))
            normalized["force_fail"] = bool(request.preferences.get("force_save_failure"))
        return normalized, None

    @staticmethod
    def _duration_from_result(tool_name: str, result: ToolResult, fallback: float) -> float:
        if not result.success:
            return fallback
        if tool_name == "search_materials":
            return float(result.data.get("material_duration", fallback))
        if tool_name == "generate_script":
            return float(result.data.get("script_duration", fallback))
        if tool_name == "estimate_cost":
            return float(result.data.get("total_duration_minutes", fallback))
        return fallback

    def _dependencies_met(self, step: TaskStep, existing: list[TaskStep]) -> bool:
        success = {s.step_id for s in existing if s.status == StepStatus.SUCCESS}
        return all(dep in success for dep in step.dependencies)

    @staticmethod
    def _actual_cost(tool_name: str, result: ToolResult) -> float:
        if not result.success: return 0.0
        if tool_name == "estimate_cost": return float(result.data.get("total_cost", 0))
        if tool_name == "generate_script": return float(result.data.get("script_cost", 0))
        if tool_name == "search_materials": return float(result.data.get("material_cost", 0))
        return 0.0

    @staticmethod
    def _summary(result: ToolResult) -> dict[str, Any]:
        return {"success": result.success, "error": result.error, "partial": result.partial, "retryable": result.retryable, "keys": list(result.data), "data": result.data}

    def _trace(self, task_id: str, step: str, plan: dict[str, Any], action: str, tool_name: Any, arguments: dict[str, Any], result_summary: dict[str, Any], status_change: str, next_action: str, duration: float, mode: AgentMode, final_result: str | None = None, replanning_reason: str | None = None) -> None:
        event = TraceEvent(task_id=task_id, step=step, plan=self._compact_plan(plan), action=action, tool_name=tool_name if isinstance(tool_name, str) else None, arguments=arguments if isinstance(arguments, dict) else {}, result_summary=result_summary, status_change=status_change, next_action=next_action, duration_seconds=duration, mode=mode, final_result=final_result, replanning_reason=replanning_reason)
        self.db.add_trace(event)

    @staticmethod
    def _compact_plan(plan: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in plan.items() if k in {"variant", "last_tool", "request", "estimate_result", "material_ids"}}

    def _result(self, request: PlanningRequest, status: TaskStatus, message: str, missing: list[str] | None = None, proposal_id: str | None = None) -> AgentResult:
        proposal = self.db.get_proposal(request.task_id)
        if proposal and not proposal_id: proposal_id = proposal[0]
        steps = self.db.get_steps(request.task_id)
        estimate = next((s.result for s in reversed(steps) if s.tool_name == "estimate_cost" and s.status == StepStatus.SUCCESS), None) or {}
        details = {key: estimate[key] for key in ("remaining_budget", "meets_budget", "meets_deadline", "deadline_gap_hours") if key in estimate}
        return AgentResult(task_id=request.task_id, status=status, message=message, proposal_id=proposal_id, missing_fields=missing or [], steps=steps, traces=self.db.get_traces(request.task_id), budget=request.budget, total_cost=estimate.get("total_cost"), total_duration=estimate.get("total_duration_minutes"), constraint_details=details)
