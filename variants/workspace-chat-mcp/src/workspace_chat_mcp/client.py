"""AnythingLLM API client for the workspace chat MCP server."""

import os
from dataclasses import dataclass

import httpx


@dataclass
class AnythingLLMConfig:
    base_url: str = "http://localhost:3001/api/v1"
    api_key: str = ""

    @classmethod
    def from_env(cls) -> "AnythingLLMConfig":
        return cls(
            base_url=os.environ.get("ANYTHINGLLM_BASE_URL", "http://localhost:3001/api/v1"),
            api_key=os.environ.get("ANYTHINGLLM_API_KEY", ""),
        )


class AnythingLLMClient:
    def __init__(self, config: AnythingLLMConfig | None = None):
        self.config = config or AnythingLLMConfig.from_env()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def list_workspaces(self) -> list[dict]:
        client = await self._get_client()
        response = await client.get("/workspaces")
        response.raise_for_status()
        data = response.json()
        return data.get("workspaces", data if isinstance(data, list) else [])

    async def chat(
        self,
        slug: str,
        message: str,
        mode: str = "query",
        thread_id: str | None = None,
    ) -> str:
        client = await self._get_client()
        payload: dict = {"message": message, "mode": mode}
        if thread_id:
            payload["threadId"] = thread_id
        response = await client.post(f"/workspace/{slug}/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("reply", data.get("response", str(data)))

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "AnythingLLMClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()