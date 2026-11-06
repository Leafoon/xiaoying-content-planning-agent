from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models.schemas import ToolResult


class MaterialTool:
    name = "search_materials"

    def __init__(self, data_path: str | Path | None = None) -> None:
        path = Path(data_path or Path(__file__).resolve().parents[2] / "data" / "materials.json")
        self.materials = json.loads(path.read_text(encoding="utf-8"))
        self.calls = 0

    def __call__(self, topic: str, preferences: dict[str, Any] | None = None, variant: str = "standard", fail_once: bool = False, force_fail: bool = False, **_: Any) -> ToolResult:
        self.calls += 1
        preferences = preferences or {}
        if force_fail or preferences.get("force_material_failure"):
            return ToolResult(success=False, error="素材库暂时不可用", retryable=True)
        if (fail_once or preferences.get("fail_material_once")) and self.calls == 1:
            return ToolResult(success=False, error="素材检索超时", retryable=True)
        matched = [m for m in self.materials if variant in m["variants"] and (topic in m["topics"] or "通用" in m["topics"])]
        if not matched:
            return ToolResult(success=False, error=f"没有找到 {variant} 素材", retryable=False)
        partial = bool(preferences.get("partial_material"))
        selected = matched[:1] if partial else matched
        return ToolResult(success=True, partial=partial, data={"materials": selected, "variant": variant, "material_cost": sum(m["cost"] for m in selected), "material_duration": sum(m["duration"] for m in selected)}, duration_seconds=0.02)
