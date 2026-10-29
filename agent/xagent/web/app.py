"""xagent Web 服务。

浏览器通过普通 HTTP + Server-Sent Events 消费 ``AgentSession.send()`` 的
事件流。API Key、工具执行和文件系统访问全部留在服务端。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from core import AgentEvent, ChatModel, Settings
from core.events import (
    RunFailed,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
)

from .sessions import SessionStore, WebSession

STATIC_DIR = Path(__file__).resolve().parent / "static"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MAX_PROMPT_CHARS = 20_000


def create_app(
    *,
    settings: Settings,
    base_dir: str | Path | None = None,
    model: ChatModel | None = None,
    session_ttl: float = 2 * 60 * 60,
) -> Starlette:
    """创建 Web 应用；``model`` 仅用于测试或替换模型实现。"""

    store = SessionStore(
        settings=settings,
        base_dir=base_dir,
        model=model,
        session_ttl=session_ttl,
    )

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        cleanup = asyncio.create_task(store.cleanup_loop())
        try:
            yield
        finally:
            cleanup.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup
            await store.close_all()

    async def index(_: Request) -> Response:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    async def health(_: Request) -> Response:
        return JSONResponse({"ok": True})

    async def bootstrap(request: Request) -> Response:
        session, error = _session_for(request, store)
        if error is not None:
            return error
        assert session is not None
        return _json(
            {
                "session_id": session.id,
                "model": session.agent.model_name,
                "directory": str(session.agent.working_directory),
                "tools": list(session.agent.tool_names),
                "history": session.transcript,
            },
            session.id,
        )

    async def chat(request: Request) -> Response:
        session, error = _session_for(request, store)
        if error is not None:
            return error
        assert session is not None

        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            return _json({"error": "请求体必须是 JSON"}, session.id, status=400)
        if not isinstance(payload, dict):
            return _json({"error": "请求体必须是 JSON 对象"}, session.id, status=400)

        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return _json({"error": "提示词不能为空"}, session.id, status=400)
        prompt = prompt.strip()
        if len(prompt) > MAX_PROMPT_CHARS:
            return _json(
                {"error": f"提示词不能超过 {MAX_PROMPT_CHARS} 个字符"},
                session.id,
                status=400,
            )
        if session.lock.locked():
            return _json(
                {"error": "当前任务尚未完成，请稍候或取消后再试"},
                session.id,
                status=409,
            )

        async def event_stream() -> AsyncIterator[str]:
            yield ": connected\n\n"
            try:
                async with session.lock:
                    session.last_seen = time.monotonic()
                    async for event in session.agent.send(prompt):
                        item = _event_item(event)
                        session.transcript.append(item)
                        yield _sse(item)
            except asyncio.CancelledError:
                session.transcript.append({"type": "cancelled", "data": {}, "at": time.time()})
                raise
            except Exception as exc:  # noqa: BLE001 - 服务端异常也要以事件返回
                item = {
                    "type": "error",
                    "data": {"message": f"{type(exc).__name__}: {exc}"},
                    "at": time.time(),
                }
                session.transcript.append(item)
                yield _sse(item)
            finally:
                session.last_seen = time.monotonic()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "X-Session-Id": session.id,
            },
        )

    async def reset(request: Request) -> Response:
        session, error = _session_for(request, store)
        if error is not None:
            return error
        assert session is not None
        if session.lock.locked():
            return _json(
                {"error": "当前任务尚未完成，无法开始新会话"},
                session.id,
                status=409,
            )
        session.agent.reset()
        session.transcript.clear()
        session.last_seen = time.monotonic()
        return _json({"ok": True}, session.id)

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/api/health", health),
            Route("/api/bootstrap", bootstrap),
            Route("/api/chat", chat, methods=["POST"]),
            Route("/api/reset", reset, methods=["POST"]),
            Mount("/static", app=StaticFiles(directory=str(STATIC_DIR)), name="static"),
        ],
        lifespan=lifespan,
    )
    return app


def _session_for(
    request: Request,
    store: SessionStore,
) -> tuple[WebSession | None, Response | None]:
    raw = request.headers.get("x-session-id", "").strip()
    if raw and not SESSION_ID_RE.fullmatch(raw):
        return None, JSONResponse(
            {"error": "无效的会话 ID"},
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )
    return store.get(raw or uuid.uuid4().hex), None


def _json(data: dict[str, Any], session_id: str, *, status: int = 200) -> JSONResponse:
    response = JSONResponse(data, status_code=status)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Session-Id"] = session_id
    return response


def _event_item(event: AgentEvent) -> dict[str, Any]:
    if isinstance(event, RunStarted):
        event_type, data = "started", {"prompt": event.prompt}
    elif isinstance(event, TextDelta):
        event_type, data = "text", {"text": event.text}
    elif isinstance(event, ToolCallStarted):
        event_type, data = "tool_start", {
            "id": event.tool_call_id,
            "name": event.name,
            "raw": event.raw_arguments,
            "arguments": event.arguments,
        }
    elif isinstance(event, ToolCallFinished):
        event_type, data = "tool_end", {
            "id": event.tool_call_id,
            "name": event.name,
            "success": event.success,
            "content": event.content,
            "payload": event.payload,
        }
    elif isinstance(event, RunFinished):
        event_type, data = "done", {
            "content": event.content,
            "rounds": event.rounds,
            "tool_calls": event.tool_calls,
        }
    elif isinstance(event, RunFailed):
        event_type, data = "error", {"message": event.message}
    else:  # 未来新增事件：旧前端可以忽略
        event_type, data = "unknown", {}
    return {"type": event_type, "data": data, "at": time.time()}


def _sse(item: dict[str, Any]) -> str:
    payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    return f"event: {item['type']}\ndata: {payload}\n\n"
