from __future__ import annotations

from typing import Any

from ..models.schemas import ToolResult


class ScriptTool:
    name = "generate_script"

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, topic: str, material_ids: list[str], variant: str = "standard", preferences: dict[str, Any] | None = None, force_fail: bool = False, **_: Any) -> ToolResult:
        self.calls += 1
        preferences = preferences or {}
        if force_fail or preferences.get("force_script_failure") or (preferences.get("fail_script_once") and self.calls == 1):
            return ToolResult(success=False, error="脚本生成服务返回错误", retryable=True)
        if not material_ids:
            return ToolResult(success=False, error="缺少素材，无法生成脚本", retryable=False)
        cost = {"high_cost": 4.0, "low_cost": 3.0, "fast": 2.0}.get(variant, 3.0)
        duration = {"high_cost": 2.0, "low_cost": 1.5, "fast": 0.5}.get(variant, 1.5)
        script = f"《{topic}》{variant} 方案：开场引入主题，展示素材亮点，加入行动号召并适配社媒发布。"
        return ToolResult(success=True, data={"script": script, "material_ids": material_ids, "script_cost": cost, "script_duration": duration, "variant": variant}, duration_seconds=0.02)
