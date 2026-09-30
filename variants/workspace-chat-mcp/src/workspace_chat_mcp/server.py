"""MCP server entry point for AnythingLLM workspace Q&A."""

import os

from mcp.server import MCPServer

from workspace_chat_mcp.client import AnythingLLMClient, AnythingLLMConfig

mcp = MCPServer("anythingllm-workspace-chat")

_client: AnythingLLMClient | None = None


def _get_client() -> AnythingLLMClient:
    global _client
    if _client is None:
        config = AnythingLLMConfig(
            base_url=os.environ.get("ANYTHINGLLM_BASE_URL", "http://localhost:3001/api/v1"),
            api_key=os.environ.get("ANYTHINGLLM_API_KEY", ""),
        )
        _client = AnythingLLMClient(config)
    return _client


@mcp.tool()
async def workspace_chat(message: str) -> str:
    """Ask a question and get an AI answer from an AnythingLLM workspace."""
    slug = os.environ.get("ANYTHINGLLM_WORKSPACE_SLUG", "")
    if not slug:
        client = _get_client()
        workspaces = await client.list_workspaces()
        if not workspaces:
            return "No workspaces found in AnythingLLM."
        slug = workspaces[0].get("slug", workspaces[0].get("name", ""))

    return await _get_client().chat(slug, message, mode="query")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()