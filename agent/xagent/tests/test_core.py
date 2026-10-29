"""core 层回归测试（不访问网络）。"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core import (
    AgentSession,
    LLMDelta,
    ToolCallDelta,
    ToolContext,
    build_default_registry,
    load_settings,
)
from core.events import RunFailed, RunFinished, ToolCallFinished, ToolCallStarted
from core.tools.search import build_search_payload, parse_search_response
from core.tools.web import extract_markdown


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
            ToolContext(
                base_dir=self.base,
                max_read_chars=20_000,
                search_api_key="test-qianfan-key",
            )
        )

    def test_registry_contents(self) -> None:
        self.assertEqual(len(self.registry.names), 13)
        self.assertEqual(self.registry.names[0], "get_date")
        self.assertIn("read_text_file", self.registry.names)
        self.assertIn("rename_path", self.registry.names)
        self.assertIn("searchweb", self.registry.names)
        self.assertIn("fet", self.registry.names)
        schemas = self.registry.specs()
        self.assertTrue(all(item["type"] == "function" for item in schemas))

    def test_config_reads_qianfan_api_key(self) -> None:
        config_path = self.base / "config.ini"
        config_path.write_text(
            "[llm]\n"
            "base_url = https://example.com\n"
            "model_name = test-model\n"
            "api_key = test-llm-key\n"
            "[search]\n"
            "baidu_qianfan_api_key = test-qianfan-key\n"
            "top_k = 7\n",
            encoding="utf-8",
        )
        settings = load_settings(config_path)
        self.assertEqual(settings.search_api_key, "test-qianfan-key")
        self.assertEqual(settings.search_top_k, 7)

    def test_searchweb_argument_validation(self) -> None:
        missing = self.registry.execute("searchweb", {})
        self.assertFalse(missing.success)
        self.assertIn("缺少必需参数", missing.payload["error"])

        blank = self.registry.execute("searchweb", {"query": "   "})
        self.assertFalse(blank.success)
        self.assertIn("query 不能为空", blank.payload["error"])

    def test_search_payload(self) -> None:
        payload = build_search_payload("python 教程", 5)
        self.assertEqual(payload["search_source"], "baidu_search_v2")
        self.assertEqual(payload["messages"][0]["content"], "python 教程")
        self.assertEqual(payload["resource_type_filter"], [{"type": "web", "top_k": 5}])
        self.assertEqual(payload["edition"], "standard")

    def test_parse_search_response(self) -> None:
        response = {
            "request_id": "req-1",
            "references": [
                {
                    "title": "示例结果一",
                    "url": "https://example.com/a",
                    "content": "这是第一\u0004条摘要\n包含换行",
                    "date": "2026-10-29",
                },
                {
                    "title": "重复结果",
                    "url": "https://example.com/a",
                    "content": "重复摘要",
                },
                {
                    "title": "示例结果二",
                    "url": "https://example.com/b",
                    "content": "这是第二条摘要",
                },
                {
                    "title": "不支持的链接",
                    "url": "ftp://example.com/file",
                    "content": "忽略",
                },
            ],
        }
        results, request_id = parse_search_response(
            json.dumps(response, ensure_ascii=False).encode(),
            5,
        )
        self.assertEqual(request_id, "req-1")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "示例结果一")
        self.assertEqual(results[0]["snippet"], "这是第一 条摘要 包含换行")
        self.assertEqual(results[0]["date"], "2026-10-29")
        self.assertEqual(results[1]["url"], "https://example.com/b")

    def test_searchweb_returns_results_with_mocked_api(self) -> None:
        response = {
            "request_id": "req-2",
            "references": [
                {
                    "title": "结果一",
                    "url": "https://example.com/one",
                    "content": "第一条摘要",
                    "date": "2026-10-29",
                },
                {
                    "title": "结果二",
                    "url": "https://example.com/two",
                    "content": "第二条摘要",
                },
            ],
        }
        completed = SimpleNamespace(
            data=json.dumps(response, ensure_ascii=False).encode(),
            error=None,
        )
        with patch("core.tools.search.request", return_value=completed) as request_mock:
            execution = self.registry.execute(
                "searchweb",
                {"query": "  python   教程 ", "max_results": 2},
            )

        self.assertTrue(execution.success, execution.content)
        self.assertEqual(execution.payload["query"], "python 教程")
        self.assertEqual(execution.payload["engine"], "baidu-qianfan")
        self.assertEqual(execution.payload["count"], 2)
        self.assertEqual(execution.payload["request_id"], "req-2")
        self.assertEqual(execution.payload["results"][0]["url"], "https://example.com/one")

        args, kwargs = request_mock.call_args
        self.assertEqual(args[0], self.registry.context.search_endpoint)
        self.assertIn("Authorization: Bearer test-qianfan-key", kwargs["extra_headers"])
        sent = json.loads(kwargs["body"])
        self.assertEqual(sent["messages"][0]["content"], "python 教程")
        self.assertEqual(sent["resource_type_filter"][0]["top_k"], 2)

    def test_searchweb_requires_api_key(self) -> None:
        registry = build_default_registry(ToolContext(base_dir=self.base))
        execution = registry.execute("searchweb", {"query": "python"})

        self.assertFalse(execution.success)
        self.assertIn("未配置千帆搜索 API Key", execution.payload["error"])
        self.assertEqual(execution.payload["reason"], "missing_config")

    def test_searchweb_reports_api_error(self) -> None:
        completed = SimpleNamespace(
            data=json.dumps(
                {
                    "code": 216003,
                    "message": "Authentication error",
                    "request_id": "req-error",
                },
                ensure_ascii=False,
            ).encode(),
            error=None,
        )
        with patch("core.tools.search.request", return_value=completed):
            execution = self.registry.execute("searchweb", {"query": "python"})

        self.assertFalse(execution.success)
        self.assertIn("216003", execution.payload["error"])
        self.assertIn("Authentication error", execution.payload["error"])
        self.assertIn("baidu_qianfan_api_key", execution.payload["error"])
        self.assertEqual(execution.payload["reason"], "api_error")
        self.assertEqual(execution.payload["api_code"], 216003)
        self.assertEqual(execution.payload["request_id"], "req-error")

    def test_searchweb_maps_http_auth_error(self) -> None:
        response = SimpleNamespace(
            data=b"",
            error=(
                "网页访问失败（HTTP 错误状态码）: curl: (22) "
                "The requested URL returned error: 401"
            ),
        )
        with patch("core.tools.search.request", return_value=response):
            execution = self.registry.execute("searchweb", {"query": "python"})

        self.assertFalse(execution.success)
        self.assertIn("HTTP 401", execution.payload["error"])
        self.assertIn("鉴权失败", execution.payload["error"])
        self.assertIn("baidu_qianfan_api_key", execution.payload["error"])
        self.assertEqual(execution.payload["reason"], "auth_error")

    def test_searchweb_reports_invalid_json(self) -> None:
        completed = SimpleNamespace(data=b"not-json", error=None)
        with patch("core.tools.search.request", return_value=completed):
            execution = self.registry.execute("searchweb", {"query": "python"})

        self.assertFalse(execution.success)
        self.assertIn("非法 JSON", execution.payload["error"])
        self.assertEqual(execution.payload["reason"], "invalid_response")

    def test_searchweb_reports_no_results(self) -> None:
        completed = SimpleNamespace(
            data=json.dumps({"references": []}).encode(),
            error=None,
        )
        with patch("core.tools.search.request", return_value=completed):
            execution = self.registry.execute("searchweb", {"query": "python"})

        self.assertFalse(execution.success)
        self.assertIn("没有返回可用的网页结果", execution.payload["error"])
        self.assertEqual(execution.payload["reason"], "no_results")

    def test_searchweb_reports_network_failure(self) -> None:
        response = SimpleNamespace(data=b"", error="请求超时（超过 15 秒）")
        with patch("core.tools.search.request", return_value=response):
            execution = self.registry.execute("searchweb", {"query": "python"})

        self.assertFalse(execution.success)
        self.assertIn("搜索请求超时", execution.payload["error"])
        self.assertEqual(execution.payload["reason"], "timeout")

    def test_fet_argument_validation(self) -> None:
        missing = self.registry.execute("fet", {})
        self.assertFalse(missing.success)
        self.assertIn("缺少必需参数", missing.payload["error"])

        unsupported = self.registry.execute("fet", {"url": "file:///etc/passwd"})
        self.assertFalse(unsupported.success)
        self.assertIn("http", unsupported.payload["error"])

    def test_extract_markdown(self) -> None:
        html = """
        <html><head>
          <title>示例页面</title>
          <style>body { color: red }</style>
          <script>console.log("noise")</script>
        </head><body>
          <nav>导航链接</nav>
          <header>页头广告</header>
          <article>
            <h1>正文标题<a href="#top">¶</a></h1>
            <p>这是第一段正文，包含足够多的内容用于验证正文提取逻辑，
               并且确保 trafilatura 能够识别出这是一个真实的内容区块。</p>
            <h2>小节标题</h2>
            <ul>
              <li>列表项一</li>
              <li>列表项二 <a href="https://example.com/b">链接二</a></li>
            </ul>
            <table>
              <thead><tr><th>名称</th><th>数量</th></tr></thead>
              <tbody>
                <tr><td>苹果</td><td>3</td></tr>
                <tr><td>香蕉</td><td>5</td></tr>
              </tbody>
            </table>
            <p>这是第二段正文，脚本和导航都不应该出现在最终结果里，
               同时正文需要被转换成 Markdown 格式返回给模型。</p>
            <p>这是第三段正文，用来增加内容长度，避免提取器把短文误判为噪声。
               正文中还可以包含 <a href="https://example.com">链接</a>。</p>
          </article>
          <footer>版权信息</footer>
        </body></html>
        """
        content = extract_markdown(html, url="https://example.com")
        self.assertIsNotNone(content)
        assert content is not None
        self.assertIn("# 正文标题", content)
        self.assertIn("## 小节标题", content)
        self.assertIn("第一段正文", content)
        self.assertIn("- 列表项一", content)
        self.assertIn("| 名称 | 数量 |", content)
        self.assertIn("[链接二](https://example.com/b)", content)
        self.assertIn("https://example.com", content)
        self.assertNotIn("¶", content)
        self.assertNotIn("导航链接", content)
        self.assertNotIn("console.log", content)
        self.assertNotIn("版权信息", content)

    def test_fet_returns_markdown_with_mocked_curl(self) -> None:
        html = """
        <html><head><title>示例页面</title></head><body>
          <article>
            <h1>抓取测试</h1>
            <p>这是通过 subprocess 调用 curl 获取到的网页正文内容，
               需要被 trafilatura 转换成 Markdown 后返回。</p>
            <p>再补充一段足够长的文字，确保正文提取结果稳定可靠，
               同时验证工具返回的是原始 URL 而不是重定向后的地址。</p>
            <p>第三段内容用于满足提取器对正文长度的要求，
               并确认返回结果中包含 Markdown 文本和字符数统计。</p>
          </article>
        </body></html>
        """.encode()
        completed = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout=html,
            stderr=b"",
        )
        with patch("core.tools.curl.find_curl", return_value="curl"), patch(
            "core.tools.curl.subprocess.run", return_value=completed
        ) as run_mock:
            execution = self.registry.execute("fet", {"url": "example.com/article"})

        self.assertTrue(execution.success, execution.content)
        self.assertEqual(execution.payload["url"], "https://example.com/article")
        self.assertIn("抓取测试", execution.payload["markdown"])
        self.assertIn("Markdown", execution.payload["markdown"])
        self.assertFalse(execution.payload["truncated"])

        args, kwargs = run_mock.call_args
        self.assertIsInstance(args[0], list)
        self.assertIn("https://example.com/article", args[0])
        self.assertFalse(kwargs["shell"])
        self.assertTrue(kwargs["capture_output"])

    def test_fet_handles_subprocess_timeout(self) -> None:
        with patch("core.tools.curl.find_curl", return_value="curl"), patch(
            "core.tools.curl.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["curl"], timeout=20),
        ):
            execution = self.registry.execute("fet", {"url": "https://example.com"})

        self.assertFalse(execution.success)
        self.assertIn("请求超时", execution.payload["error"])

    def test_fet_rejects_binary_response(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout=b"%PDF-1.7\x00binary data",
            stderr=b"",
        )
        with patch("core.tools.curl.find_curl", return_value="curl"), patch(
            "core.tools.curl.subprocess.run", return_value=completed
        ):
            execution = self.registry.execute("fet", {"url": "https://example.com/a.pdf"})

        self.assertFalse(execution.success)
        self.assertIn("二进制", execution.payload["error"])

    def test_fet_reports_empty_page(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout=b"",
            stderr=b"",
        )
        with patch("core.tools.curl.find_curl", return_value="curl"), patch(
            "core.tools.curl.subprocess.run", return_value=completed
        ):
            execution = self.registry.execute("fet", {"url": "https://example.com/empty"})

        self.assertFalse(execution.success)
        self.assertIn("空内容", execution.payload["error"])

    def test_fet_reports_curl_failure(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["curl"],
            returncode=6,
            stdout=b"",
            stderr=b"Could not resolve host",
        )
        with patch("core.tools.curl.find_curl", return_value="curl"), patch(
            "core.tools.curl.subprocess.run", return_value=completed
        ):
            execution = self.registry.execute("fet", {"url": "https://bad.invalid"})

        self.assertFalse(execution.success)
        self.assertIn("无法解析主机名", execution.payload["error"])

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
