"""Web 层无头测试（不访问网络）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401
from starlette.testclient import TestClient
from xagent_core import LLMDelta, Settings
from xagent_server.app import create_app

HEADERS = {"X-Session-Id": "test-session-123"}


class ChattyModel:
    async def stream(self, messages, tools):
        yield LLMDelta(content="你好，我是 Web 测试助手。")


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.app = create_app(
            settings=Settings(
                base_url="http://test",
                model_name="chatty",
                api_key="test-key",
            ),
            base_dir=Path(self._temp.name),
            model=ChattyModel(),
        )

    def test_index_bootstrap_and_static(self) -> None:
        with TestClient(self.app) as client:
            index = client.get("/")
            self.assertEqual(index.status_code, 200)
            self.assertIn("XAGENT", index.text)

            script = client.get("/static/app.js")
            self.assertEqual(script.status_code, 200)
            self.assertIn("consumeSSE", script.text)

            bootstrap = client.get("/api/bootstrap", headers=HEADERS)
            self.assertEqual(bootstrap.status_code, 200)
            data = bootstrap.json()
            self.assertEqual(data["session_id"], HEADERS["X-Session-Id"])
            self.assertEqual(data["model"], "chatty")
            self.assertEqual(data["history"], [])
            self.assertIn("read_text_file", data["tools"])

    def test_chat_stream_history_and_reset(self) -> None:
        with TestClient(self.app) as client:
            response = client.post(
                "/api/chat",
                headers=HEADERS,
                json={"prompt": "你好"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers["content-type"])
            self.assertIn("event: started", response.text)
            self.assertIn("event: text", response.text)
            self.assertIn("你好，我是 Web 测试助手。", response.text)
            self.assertIn("event: done", response.text)

            history = client.get("/api/bootstrap", headers=HEADERS).json()["history"]
            self.assertEqual(
                [item["type"] for item in history],
                ["started", "text", "done"],
            )

            reset = client.post("/api/reset", headers=HEADERS)
            self.assertEqual(reset.status_code, 200)
            self.assertEqual(
                client.get("/api/bootstrap", headers=HEADERS).json()["history"],
                [],
            )

    def test_invalid_requests(self) -> None:
        with TestClient(self.app) as client:
            empty = client.post("/api/chat", headers=HEADERS, json={"prompt": "  "})
            self.assertEqual(empty.status_code, 400)

            invalid = client.post(
                "/api/chat",
                headers={**HEADERS, "Content-Type": "application/json"},
                content=b"not-json",
            )
            self.assertEqual(invalid.status_code, 400)

            bad_session = client.get(
                "/api/bootstrap",
                headers={"X-Session-Id": "bad id!"},
            )
            self.assertEqual(bad_session.status_code, 400)


if __name__ == "__main__":
    unittest.main()
