"""工具注册表与工具描述模型。

工具是 Agent 与外部世界交互的唯一出口。新增工具时只需构造 ``Tool`` 并注册，
Agent 编排层和 UI 层都不需要修改。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import ToolExecution
from ..skills import SkillRegistry

ToolHandler = Callable[["ToolContext", Mapping[str, Any]], str]


@dataclass(frozen=True)
class ToolContext:
    """工具执行时需要的运行环境。"""

    base_dir: Path
    max_read_chars: int = 20_000
    allowed_commands: tuple[str, ...] = ()
    search_api_key: str = ""
    search_endpoint: str = "https://qianfan.baidubce.com/v2/ai_search/web_search"
    search_top_k: int = 10
    skills: SkillRegistry | None = None


@dataclass(frozen=True)
class Tool:
    """一个可被模型调用的工具。"""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def schema(self) -> dict[str, Any]:
        """转换为 OpenAI function calling 的 schema。"""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _error_content(message: str) -> str:
    return json.dumps(
        {"success": False, "error": message},
        ensure_ascii=False,
        indent=2,
    )


class ToolRegistry:
    """工具容器：负责 schema 输出、参数校验、异常隔离和结果解析。"""

    def __init__(self, context: ToolContext) -> None:
        self._context = context
        self._tools: dict[str, Tool] = {}

    @property
    def context(self) -> ToolContext:
        return self._context

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册: {tool.name}")
        self._tools[tool.name] = tool

    def register_all(self, tools: Sequence[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def specs(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: Mapping[str, Any]) -> ToolExecution:
        """执行工具，任何异常都转换为失败 JSON，绝不向上抛出。"""

        tool = self._tools.get(name)
        if tool is None:
            return self.failure(f"未知工具: {name}")

        if not isinstance(arguments, Mapping):
            return self.failure("工具参数必须是 JSON 对象")

        missing = [
            key
            for key in tool.parameters.get("required", [])
            if key not in arguments
        ]
        if missing:
            return self.failure(f"缺少必需参数: {', '.join(missing)}")

        try:
            raw_content = tool.handler(self._context, arguments)
        except KeyError as exc:
            return self.failure(f"缺少必需参数: {exc}")
        except Exception as exc:  # noqa: BLE001 - 单个工具异常不能中断整个会话
            return self.failure(f"{type(exc).__name__}: {exc}")

        content = raw_content if isinstance(raw_content, str) else str(raw_content)
        try:
            payload = json.loads(content)
        except (TypeError, ValueError) as exc:
            return self.failure(f"工具返回了非法 JSON: {exc}")

        if not isinstance(payload, dict):
            return self.failure("工具返回值必须是 JSON 对象")

        return ToolExecution(
            success=bool(payload.get("success", False)),
            content=content,
            payload=payload,
        )

    @staticmethod
    def failure(message: str, **data: object) -> ToolExecution:
        payload: dict[str, Any] = {"success": False, "error": message, **data}
        return ToolExecution(
            success=False,
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            payload=payload,
        )
