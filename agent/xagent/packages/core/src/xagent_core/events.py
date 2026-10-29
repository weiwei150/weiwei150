"""UI 无关的 Agent 事件。

前端（TUI / Web / Desktop）只需要消费这些事件，不应直接访问模型客户端或
工具实现。新增事件类型时保持向后兼容：旧前端可以忽略未知事件。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunStarted:
    """一次用户请求开始处理。"""

    prompt: str


@dataclass(frozen=True)
class TextDelta:
    """模型流式输出的文本片段。"""

    text: str


@dataclass(frozen=True)
class ToolCallStarted:
    """模型请求调用工具，即将执行。"""

    tool_call_id: str
    name: str
    raw_arguments: str
    arguments: dict[str, Any] | None


@dataclass(frozen=True)
class ToolCallFinished:
    """工具执行完成。"""

    tool_call_id: str
    name: str
    success: bool
    content: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RunFinished:
    """一轮完整交互结束（模型不再请求工具）。"""

    content: str
    rounds: int
    tool_calls: int


@dataclass(frozen=True)
class RunFailed:
    """请求无法继续，例如网络错误或达到工具调用轮数上限。"""

    message: str


AgentEvent = RunStarted | TextDelta | ToolCallStarted | ToolCallFinished | RunFinished | RunFailed
