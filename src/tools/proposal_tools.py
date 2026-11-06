from __future__ import annotations

from typing import Any, Callable

from ..models.schemas import ToolResult


class ProposalTool:
    name = "save_proposal"

    def __init__(self, saver: Callable[[str, dict[str, Any]], tuple[str, bool]]) -> None:
        self.saver = saver

    def __call__(self, task_id: str, proposal: dict[str, Any], force_fail: bool = False, **_: Any) -> ToolResult:
        if force_fail:
            return ToolResult(success=False, error="方案存储失败", retryable=False)
        try:
            proposal_id, created = self.saver(task_id, proposal)
            return ToolResult(success=True, data={"proposal_id": proposal_id, "created": created, "proposal": proposal}, duration_seconds=0.01)
        except Exception as exc:
            return ToolResult(success=False, error=f"方案存储失败: {exc}", retryable=True)
