"""Agent 编排层。

职责：
- 维护对话历史；
- 驱动模型流式输出；
- 聚合工具调用片段；
- 执行工具并把结果回填给模型；
- 以 UI 无关的事件流暴露全过程。

这一层不导入任何 UI 库，也不直接 print。
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .events import (
    AgentEvent,
    RunFailed,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
)
from .llm import ChatModel
from .models import ToolCall
from .prompts import SYSTEM_PROMPT
from .tools.base import ToolRegistry


@dataclass
class _PendingToolCall:
    """流式拼接过程中的临时工具调用。"""

    tool_call_id: str = ""
    name: str = ""
    arguments: str = field(default="")


class AgentSession:
    """一次会话的完整状态机，可被 TUI / Web / Desktop 复用。"""

    def __init__(
        self,
        *,
        model: ChatModel,
        tools: ToolRegistry,
        system_prompt: str = SYSTEM_PROMPT,
        max_tool_rounds: int = 16,
        model_name: str = "unknown",
    ) -> None:
        self._model = model
        self._tools = tools
        self._system_prompt = system_prompt
        self._max_tool_rounds = max_tool_rounds
        self._model_name = model_name
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def working_directory(self) -> Path:
        return self._tools.context.base_dir

    @property
    def tool_names(self) -> tuple[str, ...]:
        return self._tools.names

    @property
    def messages(self) -> list[dict[str, Any]]:
        """返回对话历史快照，避免前端意外修改内部状态。"""

        return copy.deepcopy(self._messages)

    def reset(self) -> None:
        """清空对话历史，保留系统提示词。"""

        self._messages = [{"role": "system", "content": self._system_prompt}]

    async def send(self, prompt: str) -> AsyncIterator[AgentEvent]:
        """处理一条用户输入，并以异步事件流返回全过程。"""

        prompt = prompt.strip()
        if not prompt:
            yield RunFailed("提示词不能为空")
            return

        self._messages.append({"role": "user", "content": prompt})
        yield RunStarted(prompt)

        executed_tool_calls = 0

        for round_number in range(1, self._max_tool_rounds + 1):
            pending: dict[int, _PendingToolCall] = {}
            reply_parts: list[str] = []

            try:
                async for delta in self._model.stream(
                    self._messages,
                    self._tools.specs(),
                ):
                    if delta.content:
                        reply_parts.append(delta.content)
                        yield TextDelta(delta.content)

                    if delta.tool_call is not None:
                        incoming = delta.tool_call
                        slot = pending.setdefault(incoming.index, _PendingToolCall())
                        if incoming.id:
                            slot.tool_call_id = incoming.id
                        if incoming.name:
                            slot.name = incoming.name
                        if incoming.arguments:
                            slot.arguments += incoming.arguments
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 网络/鉴权/模型异常都不能击穿事件流
                yield RunFailed(f"{type(exc).__name__}: {exc}")
                return

            reply = "".join(reply_parts)

            if not pending:
                self._messages.append({"role": "assistant", "content": reply})
                yield RunFinished(
                    content=reply,
                    rounds=round_number,
                    tool_calls=executed_tool_calls,
                )
                return

            tool_calls = self._build_tool_calls(pending)
            self._messages.append(
                {
                    "role": "assistant",
                    "content": reply or None,
                    "tool_calls": [call.as_openai_dict() for call in tool_calls],
                }
            )

            for call in tool_calls:
                arguments, parse_error = self._parse_arguments(call.raw_arguments)
                yield ToolCallStarted(
                    tool_call_id=call.tool_call_id,
                    name=call.name,
                    raw_arguments=call.raw_arguments,
                    arguments=arguments,
                )

                if parse_error is not None:
                    execution = ToolRegistry.failure(parse_error)
                else:
                    execution = self._tools.execute(call.name, arguments or {})

                yield ToolCallFinished(
                    tool_call_id=call.tool_call_id,
                    name=call.name,
                    success=execution.success,
                    content=execution.content,
                    payload=execution.payload,
                )

                self._messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.tool_call_id,
                        "content": execution.content,
                    }
                )
                executed_tool_calls += 1

        yield RunFailed(
            f"达到最大工具调用轮数 ({self._max_tool_rounds})，已停止本轮处理"
        )

    async def aclose(self) -> None:
        """释放模型客户端资源（如果实现提供了 aclose）。"""

        close = getattr(self._model, "aclose", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _build_tool_calls(pending: dict[int, _PendingToolCall]) -> list[ToolCall]:
        return [
            ToolCall(
                tool_call_id=slot.tool_call_id,
                name=slot.name,
                raw_arguments=slot.arguments,
            )
            for _, slot in sorted(pending.items())
        ]

    @staticmethod
    def _parse_arguments(raw: str) -> tuple[dict[str, Any] | None, str | None]:
        if not raw or not raw.strip():
            return {}, None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, f"工具参数不是合法的 JSON: {exc}"
        if not isinstance(value, dict):
            return None, "工具参数必须是 JSON 对象"
        return value, None
