# Workspace Chat MCP

Alternative AnythingLLM MCP implementation with the `workspace_chat` tool.

## Configuration

Set these environment variables before starting the server:

- `ANYTHINGLLM_API_KEY` (required): AnythingLLM API key.
- `ANYTHINGLLM_BASE_URL` (optional): API base URL; defaults to `http://localhost:3001/api/v1`.
- `ANYTHINGLLM_WORKSPACE_SLUG` (optional): workspace slug. If omitted, the first available workspace is used.

Install this variant with `pip install -e variants/workspace-chat-mcp` from the repository root, or from this directory with `pip install -e .`. Run it with `anythingllm-workspace-chat-mcp`. It uses the separate `workspace_chat_mcp` Python package so it can coexist with the main server.