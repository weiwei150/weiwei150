"""对话消息组件。

视觉层只负责展示。工具结果默认折叠，避免长 JSON 占满屏幕。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.widgets import Collapsible, Markdown, Static

MAX_TOOL_PREVIEW = 1800


def _now() -> str:
    return datetime.now().strftime("%H:%M")


def _one_line(value: object, limit: int = 120) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _truncate(text: str, limit: int = MAX_TOOL_PREVIEW) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（预览已截断）"


def _role_header(icon: str, label: str) -> Horizontal:
    """角色行：左侧图标 + 名称，右侧时间。"""

    return Horizontal(
        Static(Text(f"{icon} {label}"), classes="role-name"),
        Static(Text(_now()), classes="role-time"),
        classes="role",
    )


class UserMessage(Vertical):
    """用户输入。"""

    def __init__(self, text: str) -> None:
        super().__init__(
            _role_header("❯", "你"),
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
            _role_header("✦", "XAgent"),
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
    """一次工具调用：标题、摘要、可折叠的完整参数与结果。"""

    def __init__(
        self,
        name: str,
        raw_arguments: str,
        arguments: dict[str, Any] | None,
    ) -> None:
        self._name = name
        self._raw_arguments = raw_arguments
        self._arguments = arguments

        self._header = Static(Text(f"⚙ {name}"), classes="tool-header")
        self._summary = Static(Text("◌ 正在执行…"), classes="tool-summary")
        self._detail = Static(
            Text(self._format_detail(None), overflow="fold"),
            classes="tool-detail",
        )
        self._collapsible = Collapsible(
            self._detail,
            title="参数与结果",
            collapsed=True,
            collapsed_symbol="▸",
            expanded_symbol="▾",
            classes="tool-details",
        )

        super().__init__(
            self._header,
            self._summary,
            self._collapsible,
            classes="message tool tool-pending",
        )

    def _format_arguments(self) -> str:
        if self._arguments is None:
            return self._raw_arguments or "(无参数)"
        return json.dumps(self._arguments, ensure_ascii=False, indent=2)

    def _format_detail(self, result: str | None) -> str:
        parts = [f"参数\n{self._format_arguments()}"]
        if result is not None:
            parts.append(f"结果\n{result}")
        return _truncate("\n\n".join(parts))

    def _summary_text(self, success: bool, payload: dict[str, Any]) -> str:
        if not success:
            return f"✗ {_one_line(payload.get('error') or '执行失败')}"

        parts: list[str] = []
        if "count" in payload:
            parts.append(f"共 {payload['count']} 项")
        if "deleted_files" in payload:
            parts.append(f"删除 {payload['deleted_files']} 个文件")
        if "replaced" in payload:
            parts.append(f"替换 {payload['replaced']} 处")
        if "datetime" in payload:
            parts.append(_one_line(payload["datetime"], 40))
        if not parts and "path" in payload:
            parts.append(_one_line(payload["path"], 80))
        if not parts and "directory" in payload:
            parts.append(_one_line(payload["directory"], 80))
        if not parts:
            parts.append("执行成功")
        return "✓ " + " · ".join(parts)

    def finish(self, success: bool, content: str, payload: dict[str, Any]) -> None:
        self.remove_class("tool-pending")
        self.add_class("tool-ok" if success else "tool-error")

        self._summary.update(Text(self._summary_text(success, payload)))
        self._detail.update(
            Text(self._format_detail(content), overflow="fold")
        )


class SystemNotice(Static):
    """系统提示 / 命令反馈。"""

    def __init__(self, text: str) -> None:
        super().__init__(Text(f"ℹ {text}"), classes="message meta")


class ErrorNotice(Static):
    """错误信息。"""

    def __init__(self, text: str) -> None:
        super().__init__(Text(f"✖ {text}"), classes="message error")
