# 第一次更新

一个基于 MCP 协议 2026-07-28 的 Python MCP Server，桥接 AnythingLLM 的工作区能力。

## 功能

**MVP 唯一功能**：从指定工作区提取信息进行 AI 回答。

- **工具**: `query_workspace(question, workspace_slug)` - 向 AnythingLLM 工作区提问并获取 AI 回答

## 快速开始

### 安装

```bash
pip install mcp>=2.0.0 httpx anyio
pip install -e .
```

### 启动

stdio 模式（默认，供 Claude Desktop 等通过子进程接入）：

```bash
anythingllm-mcp
# 或
python -m anythingllm_mcp.server
```

Streamable HTTP 模式（供 xAgent 等通过 URL 接入）：

```bash
python -m anythingllm_mcp.server --transport streamable-http --host 127.0.0.1 --port 8091
# 或
anythingllm-mcp --transport streamable-http --port 8091
# 或
anythingllm-mcp-http --port 8091
```

默认地址为 `http://127.0.0.1:8091/mcp`。也可以用环境变量配置：
`ANYTHINGLLM_MCP_TRANSPORT`、`ANYTHINGLLM_MCP_HOST`、`ANYTHINGLLM_MCP_PORT`、
`ANYTHINGLLM_MCP_PATH`。

### 配置

环境变量：
- `ANYTHINGLLM_BASE_URL` - AnythingLLM API 基础 URL（默认: `http://localhost:3001/api`）
- `ANYTHINGLLM_API_KEY` - AnythingLLM API Key（必填，请通过环境变量设置）

### 使用

将此 MCP Server 配置到 Claude Desktop 或其他 MCP 主机即可通过 `query_workspace` 工具与 AnythingLLM 工作区交互。

## 项目结构

```
anythingllm-mcp-server/
├── pyproject.toml
├── src/
│   └── anythingllm_mcp/
│       ├── __init__.py
│       ├── server.py       # MCP Server 主入口
│       ├── anythingllm.py  # AnythingLLM API 客户端
│       └── config.py       # 配置管理
├── PLAN.md
└── README.md
```

## 其他实现

`variants/workspace-chat-mcp/` 提供另一套 AnythingLLM MCP 实现，使用 `workspace_chat` 工具，并支持通过环境变量选择工作区。

## 技术栈

- MCP 协议 2026-07-28
- MCP Python SDK v2.x (`mcp>=2.0.0`)
- httpx (HTTP 客户端)
- stdio 传输
