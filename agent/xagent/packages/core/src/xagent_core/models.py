"""核心领域对象。

这些对象只描述 Agent 内部的数据，不依赖任何 UI 框架。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    """模型请求调用的一次工具。"""

    tool_call_id: str
    name: str
    raw_arguments: str

    def as_openai_dict(self) -> dict[str, Any]:
        return {
            "id": self.tool_call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.raw_arguments,
            },
        }


@dataclass(frozen=True)
class ToolExecution:
    """工具执行结果，同时保留原始 JSON 字符串和解析后的结构。"""

    success: bool
    content: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    """可选的 token 用量信息，便于未来 Web / Desktop 展示。"""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
