"""TUI 无头测试：验证消息渲染、输入提交和斜杠命令。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core import AgentSession, LLMDelta, ToolContext, build_default_registry
from tui.app import XAgentApp
from tui.widgets import AssistantMessage, ChatView, PromptInput
from tui.widgets.messages import SystemNotice


class ChattyModel:
    async def stream(self, messages, tools):
        yield LLMDelta(content="你好，我是测试助手。")


class TuiTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_round_and_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            registry = build_default_registry(ToolContext(base_dir=Path(temp)))
            session = AgentSession(
                model=ChattyModel(),
                tools=registry,
                model_name="chatty",
            )
            app = XAgentApp(session=session)

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.2)
                chat = app.query_one(ChatView)
                prompt = app.query_one(PromptInput)

                self.assertGreaterEqual(len(chat.children), 1)

                prompt.value = "你好"
                await pilot.press("enter")

                for _ in range(80):
                    if not app._busy:
                        break
                    await pilot.pause(0.05)

                assistants = list(chat.query(AssistantMessage))
                self.assertTrue(assistants)
                self.assertEqual(assistants[-1].text, "你好，我是测试助手。")
                self.assertFalse(prompt.disabled)

                prompt.value = "/help"
                await pilot.press("enter")
                await pilot.pause(0.1)
                notices = [child for child in chat.children if isinstance(child, SystemNotice)]
                self.assertTrue(any("可用命令" in str(item.render()) for item in notices))

                prompt.value = "/new"
                await pilot.press("enter")
                await pilot.pause(0.1)
                self.assertEqual(len(session.messages), 1)

                prompt.value = "/status"
                await pilot.press("enter")
                await pilot.pause(0.1)
                self.assertTrue(
                    any("chatty" in str(item.render()) for item in chat.children)
                )


if __name__ == "__main__":
    unittest.main()
