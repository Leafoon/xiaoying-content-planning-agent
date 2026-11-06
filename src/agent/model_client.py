from __future__ import annotations

import json
from typing import Any, Protocol

from ..models.schemas import Decision, TaskStatus


class ModelClient(Protocol):
    mode: str

    def decide(self, state: dict[str, Any], tools: list[dict[str, Any]]) -> Decision:
        ...


class RealModelClient:
    """OpenAI tool-calling adapter. The engine remains independent from the SDK."""

    mode = "real"

    def __init__(self, api_key: str | None, model: str | None = None, base_url: str | None = None) -> None:
        if not api_key:
            raise ValueError("Real 模式需要 OPENAI_API_KEY")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ValueError("Real 模式需要安装 openai") from exc
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model or "gpt-4o-mini"

    def decide(self, state: dict[str, Any], tools: list[dict[str, Any]]) -> Decision:
        system = (
            "你是内容任务规划 Agent。根据当前状态和工具观察动态决定下一步。"
            "只能调用提供的工具，必须遵守预算和截止时间。工具失败时可改变方案或停止。"
            "完成保存后返回 action=finish。不要输出隐藏思维链，只提供简短 reason。"
        )
        user = json.dumps(state, ensure_ascii=False, default=str)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=tools,
            tool_choice="auto",
        )
        message = response.choices[0].message
        if message.tool_calls:
            call = message.tool_calls[0]
            args = json.loads(call.function.arguments or "{}")
            return Decision(action="tool_call", tool_name=call.function.name, arguments=args, reason="真实模型根据当前观察选择工具")
        content = message.content or "{}"
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return Decision(action="finish", final_status=TaskStatus.INCOMPLETE, message=content, reason="真实模型未返回可执行工具调用")
        return Decision.model_validate(payload)
