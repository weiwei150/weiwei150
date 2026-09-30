"""AnythingLLM MCP Server - main entry point."""

from mcp.server import MCPServer

from anythingllm_mcp.anythingllm import AnythingLLMClient
from anythingllm_mcp.config import ANYTHINGLLM_BASE_URL, ANYTHINGLLM_API_KEY

mcp = MCPServer("anythingllm")

_client: AnythingLLMClient | None = None


def get_client() -> AnythingLLMClient:
    global _client
    if _client is None:
        _client = AnythingLLMClient(ANYTHINGLLM_BASE_URL, ANYTHINGLLM_API_KEY)
    return _client


@mcp.tool()
async def query_workspace(question: str, workspace_slug: str) -> str:
    """从指定工作区的文档中提取信息进行AI回答。

    Args:
        question: 用户提出的问题
        workspace_slug: 目标工作区的唯一标识符 (slug)
    """
    client = get_client()
    try:
        answer = await client.stream_chat(
            slug=workspace_slug,
            message=question,
            options={"temperature": 0.7, "topN": 4},
        )
        if not answer.strip():
            return "该工作区未返回有效回答，请确认工作区中有已嵌入的文档。"
        return answer
    except Exception as e:
        return f"查询工作区时出错: {str(e)}"


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
