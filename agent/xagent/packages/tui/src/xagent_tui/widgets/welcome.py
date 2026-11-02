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
            Static(Text("xagent"), classes="welcome-title"),
            Static(
                Text("AI terminal agent · local tools · Textual TUI"),
                classes="welcome-subtitle",
            ),
            Static("", classes="welcome-rule"),
            _row("cwd", directory),
            _row("model", model_name),
            _row("quick start", "列出当前目录 · 读取 README.md · 创建 notes.md"),
            _row("keys", "/help 命令 · Esc 取消 · Ctrl+N 新会话 · Ctrl+Q 退出"),
            classes="welcome",
        )
