"""工具包：对外只暴露注册表、上下文和默认工具集合。"""

from __future__ import annotations

from .base import Tool, ToolContext, ToolRegistry
from .filesystem import build_filesystem_tools
from .system import build_system_tools


def build_default_registry(context: ToolContext) -> ToolRegistry:
    """按固定顺序注册默认工具。"""

    registry = ToolRegistry(context)
    registry.register_all(build_system_tools())
    registry.register_all(build_filesystem_tools())
    return registry


__all__ = [
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "build_default_registry",
]
