"""Web 会话存储。"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xagent_core import AgentSession, ChatModel, Settings, create_session


@dataclass
class WebSession:
    """一个浏览器会话对应的 Agent 和 UI 事件记录。"""

    id: str
    agent: AgentSession
    transcript: list[dict[str, Any]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_seen: float = field(default_factory=time.monotonic)


class SessionStore:
    """按会话 ID 管理 AgentSession，并清理长期不活跃的会话。"""

    def __init__(
        self,
        *,
        settings: Settings,
        base_dir: str | Path | None = None,
        model: ChatModel | None = None,
        session_ttl: float = 2 * 60 * 60,
        cleanup_interval: float = 5 * 60,
    ) -> None:
        self._settings = settings
        self._base_dir = base_dir
        self._model = model
        self._session_ttl = session_ttl
        self._cleanup_interval = cleanup_interval
        self._sessions: dict[str, WebSession] = {}

    def get(self, session_id: str) -> WebSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = WebSession(
                id=session_id,
                agent=create_session(
                    self._settings,
                    base_dir=self._base_dir,
                    model=self._model,
                ),
            )
            self._sessions[session_id] = session
        session.last_seen = time.monotonic()
        return session

    async def cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self._cleanup_interval)
            await self.prune()

    async def prune(self) -> None:
        cutoff = time.monotonic() - self._session_ttl
        stale = [
            session
            for session in self._sessions.values()
            if session.last_seen < cutoff and not session.lock.locked()
        ]
        for session in stale:
            self._sessions.pop(session.id, None)
            with suppress(Exception):
                await session.agent.aclose()

    async def close_all(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for session in sessions:
            with suppress(Exception):
                await session.agent.aclose()
