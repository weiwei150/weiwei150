"""对话区域。"""

from __future__ import annotations

import time
from typing import Any

from textual.containers import VerticalScroll

from .messages import (
    AssistantMessage,
    ErrorNotice,
    SystemNotice,
    ToolCallMessage,
    UserMessage,
)
from .welcome import WelcomePanel


class ChatView(VerticalScroll):
    """可滚动的消息列表，负责挂载消息和跟随输出。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._last_follow = 0.0

    def add_welcome(self, directory: str, model_name: str) -> None:
        self.mount(WelcomePanel(directory, model_name))
        self.follow_stream(force=True)

    def add_system(self, text: str) -> None:
        self.mount(SystemNotice(text))
        self.follow_stream(force=True)

    def add_user(self, text: str) -> None:
        self.mount(UserMessage(text))
        self.follow_stream(force=True)

    def begin_assistant(self) -> AssistantMessage:
        message = AssistantMessage()
        self.mount(message)
        self.follow_stream(force=True)
        return message

    def add_tool_call(
        self,
        name: str,
        raw_arguments: str,
        arguments: dict[str, Any] | None,
    ) -> ToolCallMessage:
        message = ToolCallMessage(name, raw_arguments, arguments)
        self.mount(message)
        self.follow_stream(force=True)
        return message

    def add_error(self, text: str) -> None:
        self.mount(ErrorNotice(text))
        self.follow_stream(force=True)

    def follow_stream(self, *, force: bool = False) -> None:
        """节流自动滚动，避免每个 token 都触发布局计算。"""

        now = time.monotonic()
        if force or now - self._last_follow >= 0.06:
            self._last_follow = now
            self.scroll_end(animate=False)

    def scroll_to_end(self) -> None:
        self.scroll_end(animate=False)

    def clear_messages(self) -> None:
        for child in list(self.children):
            child.remove()
