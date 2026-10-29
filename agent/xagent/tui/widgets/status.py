"""状态栏。"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import Horizontal
from textual.widgets import Static

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class StatusBar(Horizontal):
    """显示执行状态、模型名称、工作目录，并在忙碌时播放 spinner。"""

    def __init__(self, **kwargs: Any) -> None:
        self._spinner = Static(Text("●"), classes="status-spinner status-idle")
        self._state = Static(
            Text("就绪", overflow="ellipsis", no_wrap=True),
            classes="status-state",
        )
        self._model = Static(Text("◆ -"), classes="status-model")
        self._directory = Static(Text("⌂ -"), classes="status-directory")
        self._kind = "idle"
        self._frame_index = 0
        self._timer = None
        super().__init__(
            self._spinner,
            self._state,
            self._model,
            self._directory,
            **kwargs,
        )

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.12, self._tick, pause=True)
        if self._kind == "busy":
            self._timer.resume()

    @property
    def kind(self) -> str:
        return self._kind

    def configure(self, model_name: str, directory: str) -> None:
        self._model.update(
            Text(f"◆ {model_name}", overflow="ellipsis", no_wrap=True)
        )
        self._directory.update(
            Text(f"⌂ {directory}", overflow="ellipsis", no_wrap=True)
        )

    def set_state(self, text: str, kind: str = "idle") -> None:
        self._kind = kind
        self._state.update(Text(text, overflow="ellipsis", no_wrap=True))

        if kind == "busy":
            self._frame_index = 0
            self._spinner.set_classes("status-spinner status-busy")
            self._spinner.update(Text(SPINNER_FRAMES[0]))
            if self._timer is not None:
                self._timer.resume()
        else:
            if self._timer is not None:
                self._timer.pause()
            css_class = "status-error" if kind == "error" else "status-idle"
            self._spinner.set_classes(f"status-spinner {css_class}")
            self._spinner.update(Text("●"))

    def _tick(self) -> None:
        if self._kind != "busy":
            return
        self._frame_index = (self._frame_index + 1) % len(SPINNER_FRAMES)
        self._spinner.update(Text(SPINNER_FRAMES[self._frame_index]))
