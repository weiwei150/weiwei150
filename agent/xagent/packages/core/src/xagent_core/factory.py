"""组合根：把配置、模型、工具注册表和 AgentSession 装配起来。

UI 层只调用 ``create_session``，不关心依赖如何构建。测试可以注入 Fake ChatModel。
"""

from __future__ import annotations

from pathlib import Path

from .agent import AgentSession
from .config import Settings, load_settings
from .llm import ChatModel, OpenAIChatModel
from .tools import ToolContext, build_default_registry


def create_session(
    settings: Settings | None = None,
    *,
    base_dir: str | Path | None = None,
    model: ChatModel | None = None,
) -> AgentSession:
    """按配置创建会话；``model`` 参数用于测试或替换模型实现。"""

    resolved_settings = settings or load_settings()
    working_directory = Path(base_dir).expanduser().resolve() if base_dir else Path.cwd().resolve()

    chat_model: ChatModel = model or OpenAIChatModel(
        base_url=resolved_settings.base_url,
        api_key=resolved_settings.api_key,
        model_name=resolved_settings.model_name,
    )
    registry = build_default_registry(
        ToolContext(
            base_dir=working_directory,
            max_read_chars=resolved_settings.max_read_chars,
            allowed_commands=resolved_settings.allowed_commands,
            search_api_key=resolved_settings.search_api_key,
            search_endpoint=resolved_settings.search_endpoint,
            search_top_k=resolved_settings.search_top_k,
        )
    )

    return AgentSession(
        model=chat_model,
        tools=registry,
        max_tool_rounds=resolved_settings.max_tool_rounds,
        model_name=resolved_settings.model_name,
    )
