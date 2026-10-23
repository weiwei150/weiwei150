"""core 层回归测试（不访问网络）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core import (
    AgentSession,
    LLMDelta,
    ToolCallDelta,
    ToolContext,
    build_default_registry,
)
from core.events import RunFailed, RunFinished, ToolCallFinished, ToolCallStarted


class ScriptedModel:
    """两轮工具调用后给出最终回答。"""

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            yield LLMDelta(content="我来处理。")
            yield LLMDelta(
                tool_call=ToolCallDelta(
                    index=0,
                    id="call_1",
                    name="create_file",
                    arguments=json.dumps(
                        {
                            "directory": "sub",
                            "filename": "note.txt",
                            "content": "hello",
                        }
                    ),
                )
            )
        elif self.calls == 2:
            yield LLMDelta(
                tool_call=ToolCallDelta(
                    index=0,
                    id="call_2",
                    name="read_text_file",
                    arguments=json.dumps({"path": "sub/note.txt"}),
                )
            )
        else:
            yield LLMDelta(content="完成。")


class InvalidJsonModel:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            yield LLMDelta(
                tool_call=ToolCallDelta(
                    index=0,
                    id="bad",
                    name="list_directory",
                    arguments="not-json",
                )
            )
        else:
            yield LLMDelta(content="参数有误。")


class LoopModel:
    async def stream(self, messages, tools):
        yield LLMDelta(
            tool_call=ToolCallDelta(
                index=0,
                id="loop",
                name="get_current_directory",
                arguments="{}",
            )
        )


class CoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.base = Path(self._temp.name)
        self.registry = build_default_registry(
            ToolContext(base_dir=self.base, max_read_chars=20_000)
        )

    def test_registry_contents(self) -> None:
        self.assertEqual(len(self.registry.names), 11)
        self.assertEqual(self.registry.names[0], "get_date")
        self.assertIn("read_text_file", self.registry.names)
        self.assertIn("rename_path", self.registry.names)
        schemas = self.registry.specs()
        self.assertTrue(all(item["type"] == "function" for item in schemas))

    def test_file_lifecycle(self) -> None:
        created = self.registry.execute(
            "create_file",
            {"directory": "sub", "filename": "note.txt", "content": "hello"},
        )
        self.assertTrue(created.success, created.content)
        self.assertEqual((self.base / "sub" / "note.txt").read_text(encoding="utf-8"), "hello")

        duplicate = self.registry.execute(
            "create_file",
            {"directory": "sub", "filename": "note.txt", "content": "x"},
        )
        self.assertFalse(duplicate.success)
        self.assertIn("overwrite", duplicate.payload["error"])

        appended = self.registry.execute(
            "edit_text_file",
            {"path": "sub/note.txt", "mode": "append", "content": " world"},
        )
        self.assertTrue(appended.success, appended.content)

        replaced = self.registry.execute(
            "edit_text_file",
            {
                "path": "sub/note.txt",
                "mode": "replace",
                "old_string": "world",
                "new_string": "xagent",
            },
        )
        self.assertTrue(replaced.success, replaced.content)
        self.assertEqual(
            (self.base / "sub" / "note.txt").read_text(encoding="utf-8"),
            "hello xagent",
        )

        renamed = self.registry.execute(
            "rename_path",
            {"source": "sub/note.txt", "destination": "note.md"},
        )
        self.assertTrue(renamed.success, renamed.content)
        self.assertTrue((self.base / "sub" / "note.md").is_file())

        deleted = self.registry.execute("delete_file", {"path": "sub/note.md"})
        self.assertTrue(deleted.success, deleted.content)
        self.assertFalse((self.base / "sub" / "note.md").exists())

        removed = self.registry.execute("delete_directory", {"path": "sub"})
        self.assertTrue(removed.success, removed.content)
        self.assertFalse((self.base / "sub").exists())

    def test_protected_paths(self) -> None:
        self.assertFalse(self.registry.execute("delete_directory", {"path": str(self.base)}).success)
        self.assertFalse(self.registry.execute("delete_file", {"path": str(self.base / "x")}).success)
        self.assertFalse(
            self.registry.execute(
                "rename_path",
                {"source": str(self.base), "destination": "other"},
            ).success
        )

    def test_missing_and_invalid_arguments(self) -> None:
        missing = self.registry.execute("read_text_file", {})
        self.assertFalse(missing.success)
        self.assertIn("缺少必需参数", missing.payload["error"])

        unknown = self.registry.execute("no_such_tool", {})
        self.assertFalse(unknown.success)
        self.assertIn("未知工具", unknown.payload["error"])

    async def test_agent_runs_multiple_tool_rounds(self) -> None:
        session = AgentSession(
            model=ScriptedModel(),
            tools=self.registry,
            model_name="scripted",
            max_tool_rounds=5,
        )
        events = [event async for event in session.send("建个文件再读出来")]

        started = [event for event in events if isinstance(event, ToolCallStarted)]
        finished = [event for event in events if isinstance(event, ToolCallFinished)]
        final = [event for event in events if isinstance(event, RunFinished)]

        self.assertEqual(len(started), 2)
        self.assertTrue(all(event.success for event in finished))
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0].tool_calls, 2)
        self.assertEqual(len(session.messages), 7)
        self.assertTrue((self.base / "sub" / "note.txt").is_file())

    async def test_invalid_tool_json_isolated(self) -> None:
        session = AgentSession(
            model=InvalidJsonModel(),
            tools=self.registry,
            model_name="invalid",
        )
        events = [event async for event in session.send("测试参数")]
        started = [event for event in events if isinstance(event, ToolCallStarted)]
        finished = [event for event in events if isinstance(event, ToolCallFinished)]

        self.assertEqual(len(started), 1)
        self.assertIsNone(started[0].arguments)
        self.assertEqual(len(finished), 1)
        self.assertFalse(finished[0].success)
        self.assertIn("JSON", finished[0].payload["error"])

    async def test_max_tool_rounds(self) -> None:
        session = AgentSession(
            model=LoopModel(),
            tools=self.registry,
            max_tool_rounds=2,
        )
        events = [event async for event in session.send("无限循环")]
        self.assertTrue(any(isinstance(event, RunFailed) for event in events))


if __name__ == "__main__":
    unittest.main()
