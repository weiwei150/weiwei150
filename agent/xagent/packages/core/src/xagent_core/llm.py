"""LLM 访问层。

通过 ``ChatModel`` 协议隔离具体供应商。默认实现使用 AsyncOpenAI，
未来接入其他兼容接口或 Mock 模型时不需要修改 Agent 编排代码。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from openai import AsyncOpenAI


@dataclass(frozen=True)
class ToolCallDelta:
    """流式返回的工具调用片段。"""

    index: int
    id: str | None = None
    name: str | None = None
    arguments: str | None = None


@dataclass(frozen=True)
class LLMDelta:
    """归一化后的模型流式片段。"""

    content: str = ""
    tool_call: ToolCallDelta | None = None


class ChatModel(Protocol):
    """Agent 依赖的最小模型接口。"""

    def stream(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> AsyncIterator[LLMDelta]:
        ...


class OpenAIChatModel:
    """基于 OpenAI 兼容 Chat Completions 接口的流式实现。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout: float = 120.0,
    ) -> None:
        self.model_name = model_name
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )

    async def stream(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> AsyncIterator[LLMDelta]:
        request: dict[str, Any] = {
            "model": self.model_name,
            "messages": list(messages),
            "stream": True,
        }
        if tools:
            request["tools"] = list(tools)
            request["tool_choice"] = "auto"

        stream = await self._client.chat.completions.create(**request)

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue

            if delta.content:
                yield LLMDelta(content=delta.content)

            for tool_call in delta.tool_calls or []:
                function = tool_call.function
                yield LLMDelta(
                    tool_call=ToolCallDelta(
                        index=tool_call.index,
                        id=tool_call.id,
                        name=function.name if function else None,
                        arguments=function.arguments if function else None,
                    )
                )

    async def aclose(self) -> None:
        await self._client.close()
