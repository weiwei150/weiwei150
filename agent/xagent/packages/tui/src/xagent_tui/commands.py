"""TUI 斜杠命令解析。

命令属于表现层交互约定，core 不需要知道它们的存在。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashCommand:
    name: str
    args: str = ""


HELP_TEXT = """可用命令：
  /help            显示帮助
  /status          查看模型、工作目录和工具信息
  /new             开始新会话（清空对话历史）
  /clear           清空当前屏幕
  /quit            退出 xagent

快捷键：
  Enter            发送消息
  ↑ / ↓            浏览输入历史
  Esc              取消当前请求
  Ctrl+N           新会话
  Ctrl+L           清屏
  Ctrl+Q           退出"""


def parse_command(text: str) -> SlashCommand | None:
    """解析 ``/name args``；非命令返回 None。"""

    if not text.startswith("/"):
        return None
    body = text[1:].strip()
    if not body:
        return SlashCommand("")
    name, _, args = body.partition(" ")
    return SlashCommand(name.lower(), args.strip())
