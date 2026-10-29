"""欢迎面板。"""

from __future__ import annotations

from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.widgets import Static


def _row(label: str, value: str) -> Horizontal:
    return Horizontal(
        Static(Text(label), classes="welcome-label"),
        Static(Text(value), classes="welcome-value"),
        classes="welcome-row",
    )


class WelcomePanel(Vertical):
    """首次进入或新会话时展示的引导卡片。"""

    def __init__(self, directory: str, model_name: str) -> None:
        super().__init__(
            Static(Text("✦  XAGENT"), classes="welcome-title"),
            Static(
                Text("本地文件操作 Agent · Textual TUI"),
                classes="welcome-subtitle",
            ),
            Static("", classes="welcome-rule"),
            _row("工作目录", directory),
            _row("模型", model_name),
            _row("快速开始", "列出当前目录 · 读取 README.md · 创建 notes.md"),
            _row("提示", "/help 查看命令 · Esc 取消 · Ctrl+Q 退出"),
            classes="welcome",
        )
