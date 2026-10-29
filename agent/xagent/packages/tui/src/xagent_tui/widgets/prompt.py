"""输入组件。"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import events
from textual.containers import Horizontal
from textual.widgets import Input, Static


class PromptInput(Input):
    """Enter 提交，上下方向键浏览历史。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_index = 0

    def remember(self, text: str) -> None:
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._history_index = len(self._history)

    def on_key(self, event: events.Key) -> None:
        if not self._history:
            return

        if event.key == "up":
            event.prevent_default()
            event.stop()
            self._history_index = max(0, self._history_index - 1)
            self._load_history()
        elif event.key == "down":
            event.prevent_default()
            event.stop()
            self._history_index = min(len(self._history), self._history_index + 1)
            self._load_history()

    def _load_history(self) -> None:
        if self._history_index >= len(self._history):
            self.value = ""
        else:
            self.value = self._history[self._history_index]
        self.cursor_position = len(self.value)


class PromptBar(Horizontal):
    """带提示符的输入栏。"""

    def __init__(self, placeholder: str = "", **kwargs: Any) -> None:
        self.input = PromptInput(
            placeholder=placeholder,
            id="prompt-input",
        )
        super().__init__(
            Static(Text("❯"), classes="prompt-prefix"),
            self.input,
            **kwargs,
        )
