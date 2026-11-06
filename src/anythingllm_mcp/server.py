"""AnythingLLM MCP Server - main entry point."""

import argparse
import os

from mcp.server import MCPServer

from anythingllm_mcp.anythingllm import AnythingLLMClient
from anythingllm_mcp.config import ANYTHINGLLM_BASE_URL, ANYTHINGLLM_API_KEY

mcp = MCPServer("anythingllm")

DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8091
DEFAULT_HTTP_PATH = "/mcp"

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anythingllm-mcp",
        description="AnythingLLM MCP Server（stdio / Streamable HTTP）",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("ANYTHINGLLM_MCP_TRANSPORT", "stdio"),
        help="传输方式，默认 stdio；HTTP 方式可用 streamable-http",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("ANYTHINGLLM_MCP_HOST", DEFAULT_HTTP_HOST),
        help=f"Streamable HTTP 监听地址，默认 {DEFAULT_HTTP_HOST}",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("ANYTHINGLLM_MCP_PORT", str(DEFAULT_HTTP_PORT))),
        help=f"Streamable HTTP 监听端口，默认 {DEFAULT_HTTP_PORT}",
    )
    parser.add_argument(
        "--path",
        default=os.getenv("ANYTHINGLLM_MCP_PATH", DEFAULT_HTTP_PATH),
        help=f"Streamable HTTP 路径，默认 {DEFAULT_HTTP_PATH}",
    )
    return parser


def run_streamable_http(
    host: str = DEFAULT_HTTP_HOST,
    port: int = DEFAULT_HTTP_PORT,
    path: str = DEFAULT_HTTP_PATH,
) -> None:
    """启动 Streamable HTTP 传输，例如 http://127.0.0.1:8091/mcp。"""

    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path=path,
    )


def main_http() -> None:
    """供 anythingllm-mcp-http 命令使用。"""

    parser = build_parser()
    args = parser.parse_args()
    run_streamable_http(args.host, args.port, args.path)


def main() -> None:
    args = build_parser().parse_args()
    if args.transport == "streamable-http":
        run_streamable_http(args.host, args.port, args.path)
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
