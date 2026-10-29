"""Textual 前端。

只依赖 ``xagent_core`` 暴露的 AgentSession 和事件，不直接访问 LLM 客户端或工具实现。
"""

from __future__ import annotations

from asyncio import CancelledError
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input
from xagent_core import AgentSession, create_session
from xagent_core.events import (
    RunFailed,
    RunFinished,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
)

from .commands import HELP_TEXT, parse_command
from .widgets import ChatView, PromptBar, PromptInput, StatusBar
from .widgets.messages import AssistantMessage, ToolCallMessage


class XAgentApp(App[None]):
    """xagent 的 TUI 实现。"""

    CSS_PATH = "styles.tcss"
    TITLE = "XAgent"
    SUB_TITLE = "本地文件操作 Agent"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+q", "quit", "退出"),
        Binding("ctrl+n", "new_session", "新会话"),
        Binding("ctrl+l", "clear_chat", "清屏"),
        Binding("escape", "cancel", "取消"),
    ]

    def __init__(
        self,
        session: AgentSession | None = None,
        *,
        settings=None,
        base_dir: str | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._settings = settings
        self._base_dir = base_dir
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ChatView(id="chat")
        yield StatusBar(id="status")
        yield PromptBar(
            placeholder="输入指令，Enter 发送 · /help 查看命令",
            id="prompt-bar",
        )
        yield Footer()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._chat = self.query_one(ChatView)
        self._status = self.query_one(StatusBar)
        self._prompt = self.query_one(PromptInput)

        if self._session is None:
            try:
                self._session = create_session(
                    self._settings,
                    base_dir=self._base_dir,
                )
            except Exception as exc:  # noqa: BLE001 - 启动失败需要展示给用户
                self._chat.add_system("xagent 启动失败")
                self._chat.add_error(str(exc))
                self._status.set_state("配置错误", "error")
                self._prompt.disabled = True
                return

        self._status.configure(
            self._session.model_name,
            str(self._session.working_directory),
        )
        self._show_welcome()
        self._prompt.focus()

    async def on_unmount(self) -> None:
        if self._session is not None:
            await self._session.aclose()

    # ------------------------------------------------------------------
    # 输入与命令
    # ------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        self._prompt.remember(text)

        if text.startswith("/"):
            self._handle_command(text)
            return

        if self._busy:
            self._chat.add_system("当前任务尚未完成，请稍候或按 Esc 取消。")
            return
        if self._session is None:
            self._chat.add_system("Agent 尚未初始化，请先检查配置。")
            return

        self._chat.add_user(text)
        self._run_prompt(text)

    def _handle_command(self, text: str) -> None:
        command = parse_command(text)
        if command is None:
            return

        if command.name in {"help", "?"}:
            self._chat.add_system(HELP_TEXT)
        elif command.name in {"clear", "cls"}:
            self._chat.clear_messages()
        elif command.name == "new":
            self.action_new_session()
        elif command.name in {"quit", "exit"}:
            self.exit()
        elif command.name == "status":
            self._show_status()
        else:
            self._chat.add_system(
                f"未知命令: /{command.name}，输入 /help 查看可用命令。"
            )

    def _show_status(self) -> None:
        if self._session is None:
            self._chat.add_system("Agent 尚未初始化。")
            return
        tools = ", ".join(self._session.tool_names)
        self._chat.add_system(
            "会话状态\n"
            f"模型: {self._session.model_name}\n"
            f"工作目录: {self._session.working_directory}\n"
            f"工具({len(self._session.tool_names)}): {tools}\n"
            f"历史消息: {len(self._session.messages)} 条"
        )

    # ------------------------------------------------------------------
    # Agent 事件处理
    # ------------------------------------------------------------------

    @work(exclusive=True, group="agent")
    async def _run_prompt(self, prompt: str) -> None:
        assert self._session is not None

        self._busy = True
        self._prompt.disabled = True
        self._status.set_state("思考中…", "busy")

        assistant: AssistantMessage | None = None
        tool_blocks: dict[str, ToolCallMessage] = {}

        try:
            async for event in self._session.send(prompt):
                if isinstance(event, TextDelta):
                    if assistant is None:
                        assistant = self._chat.begin_assistant()
                    assistant.append(event.text)
                    self._chat.follow_stream()

                elif isinstance(event, ToolCallStarted):
                    if assistant is not None:
                        assistant.finish()
                        assistant = None
                    self._status.set_state(f"执行工具 · {event.name}", "busy")
                    tool_blocks[event.tool_call_id] = self._chat.add_tool_call(
                        event.name,
                        event.raw_arguments,
                        event.arguments,
                    )

                elif isinstance(event, ToolCallFinished):
                    block = tool_blocks.pop(event.tool_call_id, None)
                    if block is not None:
                        block.finish(event.success, event.content, event.payload)
                    self._status.set_state("思考中…", "busy")
                    self._chat.follow_stream()

                elif isinstance(event, RunFinished):
                    if assistant is None and event.content:
                        assistant = self._chat.begin_assistant()
                        assistant.append(event.content)
                    if assistant is not None:
                        assistant.finish()
                        assistant = None
                    if not event.content and event.tool_calls == 0:
                        self._chat.add_system("本轮没有返回文本内容。")
                    self._chat.scroll_to_end()
                    self._status.set_state("就绪", "idle")

                elif isinstance(event, RunFailed):
                    if assistant is not None:
                        assistant.finish()
                        assistant = None
                    self._chat.add_error(event.message)
                    self._chat.scroll_to_end()
                    self._status.set_state("出错", "error")

        except CancelledError:
            self._chat.add_system("已取消当前请求。")
            self._chat.scroll_to_end()
            raise
        except Exception as exc:  # noqa: BLE001 - 保证 UI 不因未知异常崩溃
            self._chat.add_error(f"{type(exc).__name__}: {exc}")
            self._chat.scroll_to_end()
            self._status.set_state("出错", "error")
        finally:
            if assistant is not None:
                assistant.finish()
            self._busy = False
            self._prompt.disabled = False
            self._prompt.focus()
            if self._status.kind != "error":
                self._status.set_state("就绪", "idle")

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------

    def action_cancel(self) -> None:
        if not self._busy:
            return
        self._status.set_state("正在取消…", "busy")
        self.workers.cancel_group(self, "agent")

    def action_new_session(self) -> None:
        if self._busy:
            self._chat.add_system("请先等待当前任务完成，或按 Esc 取消。")
            return
        if self._session is None:
            return
        self._session.reset()
        self._chat.clear_messages()
        self._show_welcome()
        self._status.set_state("就绪", "idle")
        self._prompt.focus()

    def action_clear_chat(self) -> None:
        self._chat.clear_messages()

    # ------------------------------------------------------------------

    def _show_welcome(self) -> None:
        if self._session is None:
            return
        self._chat.add_welcome(
            str(self._session.working_directory),
            self._session.model_name,
        )
