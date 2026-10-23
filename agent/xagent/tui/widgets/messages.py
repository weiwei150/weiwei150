"""对话消息组件。

所有组件只负责展示，不包含 Agent 逻辑。后续 Web / Desktop 前端可以复用
core 事件模型，而不需要复用这些 Textual 组件。
"""

from __future__ import annotations

import json
from typing import Any

from rich.text import Text
from textual.containers import Vertical
from textual.widgets import Markdown, Static

MAX_TOOL_PREVIEW = 1800


def _truncate(text: str, limit: int = MAX_TOOL_PREVIEW) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（预览已截断）"


class UserMessage(Vertical):
    """用户输入。"""

    def __init__(self, text: str) -> None:
        super().__init__(
            Static("你", classes="role"),
            Markdown(text, classes="body"),
            classes="message user",
        )


class AssistantMessage(Vertical):
    """流式助手回复；结束时切换为 Markdown 渲染。"""

    def __init__(self) -> None:
        self._buffer = ""
        self._finished = False
        self._stream_body = Static("", classes="body stream-body")
        self._final_body = Markdown("", classes="body final-body")
        self._final_body.display = False
        super().__init__(
            Static("助手", classes="role"),
            self._stream_body,
            self._final_body,
            classes="message assistant",
        )

    @property
    def text(self) -> str:
        return self._buffer

    def append(self, delta: str) -> None:
        if self._finished:
            return
        self._buffer += delta
        self._stream_body.update(Text(self._buffer))

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._stream_body.display = False
        self._final_body.update(self._buffer.strip() or "（无文本回复）")
        self._final_body.display = True


class ToolCallMessage(Vertical):
    """一次工具调用的参数与结果。"""

    def __init__(
        self,
        name: str,
        raw_arguments: str,
        arguments: dict[str, Any] | None,
    ) -> None:
        self._name = name
        self._raw_arguments = raw_arguments
        self._arguments = arguments
        self._header = Static(f"⚙ {name} · 执行中", classes="role tool-role")
        self._body = Static(
            Text(self._format_arguments(), overflow="fold"),
            classes="body tool-body",
        )
        super().__init__(
            self._header,
            self._body,
            classes="message tool tool-pending",
        )

    def _format_arguments(self) -> str:
        if self._arguments is None:
            payload = self._raw_arguments or "(无参数)"
        else:
            payload = json.dumps(self._arguments, ensure_ascii=False, indent=2)
        return _truncate(f"参数\n{payload}")

    def finish(self, success: bool, content: str, payload: dict[str, Any]) -> None:
        self.remove_class("tool-pending")
        self.add_class("tool-ok" if success else "tool-error")

        if success:
            self._header.update(f"✓ {self._name} · 完成")
            detail = content
        else:
            self._header.update(f"✗ {self._name} · 失败")
            detail = str(payload.get("error") or content)

        self._body.update(
            Text(_truncate(f"结果\n{detail}"), overflow="fold")
        )


class SystemNotice(Static):
    """系统提示 / 欢迎信息。"""

    def __init__(self, text: str) -> None:
        super().__init__(Text(text), classes="message meta")


class ErrorNotice(Static):
    """错误信息。"""

    def __init__(self, text: str) -> None:
        super().__init__(Text(f"错误：{text}"), classes="message error")
