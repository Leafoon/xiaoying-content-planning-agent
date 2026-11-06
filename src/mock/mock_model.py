from __future__ import annotations

from typing import Any

from ..models.schemas import Decision, TaskStatus


class MockModelClient:
    """Deterministic, observable policy that makes decisions from tool observations.

    It is deliberately separate from AgentRunner, so the same execution loop can
    be driven by RealModelClient. `mode=mock` is recorded in every trace.
    """

    mode = "mock"

    def decide(self, state: dict[str, Any], tools: list[dict[str, Any]]) -> Decision:
        request = state["request"]
        last = state.get("last_result") or {}
        last_tool = state.get("last_tool")
        variant = state.get("variant", request.get("preferences", {}).get("variant", "standard"))
        attempts = state.get("attempts", {})
        history = state.get("tool_history", [])
        failed_calls = sum(1 for item in history if not item.get("success"))

        if failed_calls >= 3:
            return Decision(action="finish", final_status=TaskStatus.INCOMPLETE, message="连续工具失败达到安全上限，保留已成功步骤", reason="根据连续失败观察停止")
        if last_tool == "save_proposal":
            if last.get("success"):
                return Decision(action="finish", final_status=TaskStatus.COMPLETED, message="方案已保存", reason="保存工具返回成功")
            return Decision(action="finish", final_status=TaskStatus.FAILED, message=last.get("error", "保存失败"), reason="保存失败且不可安全伪造成功")

        if last_tool == "estimate_cost" and last.get("success"):
            data = last.get("data", {})
            if data.get("meets_budget") and data.get("meets_deadline"):
                proposal = state.get("proposal", {})
                return Decision(action="tool_call", tool_name="save_proposal", arguments={"task_id": request["task_id"], "proposal": proposal, "force_fail": bool(request.get("preferences", {}).get("force_save_failure"))}, reason="成本和截止时间均满足，保存方案")
            if not data.get("meets_budget") and variant != "low_cost":
                return Decision(action="tool_call", tool_name="search_materials", arguments={"topic": request["topic"], "preferences": request.get("preferences", {}), "variant": "low_cost"}, reason="观察到预算超限，切换低成本方案")
            if not data.get("meets_deadline") and variant != "fast":
                return Decision(action="tool_call", tool_name="search_materials", arguments={"topic": request["topic"], "preferences": request.get("preferences", {}), "variant": "fast"}, reason="观察到截止时间不足，切换快速方案")
            reasons: list[str] = []
            if not data.get("meets_budget"):
                reasons.append(f"预算缺口 {abs(float(data.get('remaining_budget') or 0)):.2f}")
            if not data.get("meets_deadline"):
                reasons.append(f"截止时间不足 {abs(float(data.get('deadline_gap_hours') or 0)):.2f} 小时")
            return Decision(action="finish", final_status=TaskStatus.INCOMPLETE, message="所有可选方案均无法满足约束，" + "，".join(reasons), reason="约束观察仍不满足")

        if last_tool == "search_materials" and last.get("success"):
            materials = last["data"].get("materials", [])
            return Decision(action="tool_call", tool_name="generate_script", arguments={"topic": request["topic"], "material_ids": [m["id"] for m in materials], "variant": state.get("variant", "standard"), "preferences": request.get("preferences", {})}, reason="根据检索结果生成脚本")

        if last_tool == "generate_script" and last.get("success"):
            material_data = state.get("material_result", {}).get("data", {})
            script_data = last.get("data", {})
            return Decision(action="tool_call", tool_name="estimate_cost", arguments={"material_cost": material_data.get("material_cost", 0), "script_cost": script_data.get("script_cost", 0), "material_duration": material_data.get("material_duration", 0), "script_duration": script_data.get("script_duration", 0), "budget": request.get("budget"), "deadline": request.get("deadline"), "now": state.get("now")}, reason="根据素材和脚本结果估算成本与耗时")

        if last_tool == "search_materials" and not last.get("success"):
            # Retry only when the observed tool says it is retryable. Change the query variant.
            if last.get("retryable") and attempts.get("search_materials", 0) < 2:
                fallback = "low_cost" if request.get("budget") is not None and request["budget"] <= 10 else "standard"
                return Decision(action="tool_call", tool_name="search_materials", arguments={"topic": request["topic"], "preferences": request.get("preferences", {}), "variant": fallback}, reason="素材检索可重试，调整检索方案")
            return Decision(action="finish", final_status=TaskStatus.INCOMPLETE, message=last.get("error", "素材检索失败"), reason="素材失败不可继续")
        if last_tool == "generate_script" and not last.get("success"):
            if last.get("retryable") and attempts.get("generate_script", 0) < 2:
                return Decision(action="tool_call", tool_name="generate_script", arguments={"topic": request["topic"], "material_ids": state.get("material_ids", []), "variant": "fast", "preferences": request.get("preferences", {})}, reason="脚本失败，改用快速方案")
            return Decision(action="finish", final_status=TaskStatus.INCOMPLETE, message=last.get("error", "脚本生成失败"), reason="脚本失败不可继续")

        return Decision(action="tool_call", tool_name="search_materials", arguments={"topic": request["topic"], "preferences": request.get("preferences", {}), "variant": variant}, reason="开始检索与主题匹配的素材")
