"""AnythingLLM API client for the MCP Server."""

import httpx
import json

from anythingllm_mcp.config import ANYTHINGLLM_BASE_URL, ANYTHINGLLM_API_KEY


class AnythingLLMClient:
    def __init__(self, base_url: str = ANYTHINGLLM_BASE_URL, api_key: str = ANYTHINGLLM_API_KEY):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def list_workspaces(self) -> list[dict]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=15) as client:
            resp = await client.get("/v1/workspaces", headers=self._headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("workspaces", [])

    async def get_workspace(self, slug: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=15) as client:
            resp = await client.get(f"/v1/workspace/{slug}", headers=self._headers)
            resp.raise_for_status()
            return resp.json()

    async def stream_chat(self, slug: str, message: str, options: dict | None = None) -> str:
        body = {
            "message": message,
            "sessionId": None,
            "options": options or {"temperature": 0.7, "topN": 4},
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60) as client:
            resp = await client.post(
                f"/v1/workspace/{slug}/stream-chat",
                json=body,
                headers=self._headers,
            )
            resp.raise_for_status()

            full_text = ""
            async for line in resp.aiter_lines():
                stripped = line.strip()
                if stripped.startswith("data:"):
                    data_str = stripped[5:].strip()
                    if data_str == "[DONE]":
                        continue
                    try:
                        event = json.loads(data_str)
                        if "chunk" in event:
                            full_text += event["chunk"]
                        elif "textResponse" in event and event.get("done"):
                            pass
                        elif "text" in event:
                            full_text += event["text"]
                    except (json.JSONDecodeError, KeyError):
                        pass

            return full_text if full_text else "该工作区未返回有效回答。"

    async def list_documents(self, slug: str) -> list[dict]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=15) as client:
            resp = await client.get(f"/v1/workspace/{slug}/documents", headers=self._headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("documents", data if isinstance(data, list) else [])

    async def delete_document(self, workspace_id: str, document_id: str) -> bool:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=15) as client:
            resp = await client.delete(f"/v1/document/{workspace_id}/{document_id}", headers=self._headers)
            resp.raise_for_status()
            return True
