"""状态栏。"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import Horizontal
from textual.widgets import Static


class StatusBar(Horizontal):
    """显示运行状态、模型名称和工作目录。"""

    def __init__(self, **kwargs: Any) -> None:
        self._state = Static(Text("● 就绪"), classes="status-state")
        self._model = Static(Text("模型: -"), classes="status-model")
        self._directory = Static(Text("目录: -"), classes="status-directory")
        self._kind = "idle"
        super().__init__(self._state, self._model, self._directory, **kwargs)

    @property
    def kind(self) -> str:
        return self._kind

    def configure(self, model_name: str, directory: str) -> None:
        self._model.update(Text(f"模型: {model_name}"))
        self._directory.update(Text(f"目录: {directory}"))

    def set_state(self, text: str, kind: str = "idle") -> None:
        self._kind = kind
        styles = {
            "idle": "bold green",
            "busy": "bold yellow",
            "error": "bold red",
        }
        self._state.update(Text(f"● {text}", style=styles.get(kind, "bold")))
