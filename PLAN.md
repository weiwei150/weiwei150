# 第一次更新 MVP 开发计划

## 项目概述

开发一个基于 MCP 协议 2026-07-28 版本的 Python MCP Server，作为 AnythingLLM 的桥接层，使 LLM 主机（如 Claude Desktop）可以通过 MCP 协议与 AnythingLLM 的工作区进行交互。

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| MCP 协议版本 | 2026-07-28 | 无握手、无会话、纯请求驱动 |
| MCP SDK | `mcp>=2.0.0` | Python SDK v2，`MCPServer` + `@mcp.tool()` |
| HTTP 客户端 | `httpx` | 调用 AnythingLLM REST API |
| SSE 解析 | `httpx` + `anyio` | 处理 stream-chat 的 SSE 流 |
| 传输方式 | stdio | MCP Server 通过 stdio 与主机通信 |

## AnythingLLM API 确认信息

- **基础URL**: `http://localhost:3001/api/v1`
- **API Key**: 通过 `ANYTHINGLLM_API_KEY` 环境变量配置
- **认证方式**: `Authorization: Bearer <api-key>` Header
- **已验证工作区**:
  - 请在部署环境中指定工作区 slug
- **关键端点**:
  - `GET /v1/workspaces` - 列出所有工作区
  - `GET /v1/workspace/{slug}` - 获取工作区详情
  - `POST /v1/workspace/{slug}/stream-chat` - SSE 流式聊天
  - `POST /v1/workspace/{slug}/chat` - 同步聊天
  - `POST /v1/workspace/{slug}/vector-search` - 向量搜索

## MVP 功能定义

### 唯一功能：从单一工作区提取信息进行 AI 回答

**工具名称**: `query_workspace`

**功能描述**: 接收用户问题和工作区 slug，调用 AnythingLLM 的流式聊天接口，返回 AI 基于该工作区文档的回答。

**输入参数**:
- `question` (str, 必填): 用户提出的问题
- `workspace_slug` (str, 必填): 目标工作区的 slug

**输出**:
- AI 基于工作区文档生成的回答文本（字符串）

**内部流程**:
1. 验证 API Key 有效性（调用 `/v1/auth`）
2. 调用 AnythingLLM 的 `POST /v1/workspace/{slug}/stream-chat`
3. 解析 SSE 流式响应
4. 拼接完整回答并返回

**stream-chat 请求体**:
```json
{
  "prompt": "用户的问题",
  "options": {
    "temperature": 0.7,
    "topN": 4,
    "systemPrompt": ""
  }
}
```

## 项目结构

```
anythingllm-mcp-server/
├── pyproject.toml          # 项目依赖和配置
├── src/
│   └── anythingllm_mcp/
│       ├── __init__.py     # 包初始化
│       ├── server.py       # MCP Server 主入口
│       ├── anythingllm.py  # AnythingLLM API 客户端
│       └── config.py       # 配置（API Key, Base URL）
├── README.md               # 项目说明
└── PLAN.md                 # 本计划文件
```

## 开发步骤

### Step 1: 项目初始化
- 创建 `pyproject.toml`，声明依赖 `mcp>=2.0.0`, `httpx`, `anyio`
- 创建目录结构
- 配置 Python 3.10+ 环境

### Step 2: AnythingLLM 客户端封装 (`anythingllm.py`)
- 实现 `AnythingLLMClient` 类
- 方法: `list_workspaces()`, `get_workspace(slug)`, `stream_chat(slug, prompt, options)`
- 使用 `httpx` 发送请求，处理 SSE 流式响应
- 错误处理和重试逻辑

### Step 3: MCP Server 实现 (`server.py`)
- 使用 `MCPServer("anythingllm")` 创建服务器
- 用 `@mcp.tool()` 装饰 `query_workspace` 函数
- 实现工具处理逻辑：接收 question + workspace_slug，调用 AnythingLLM 客户端
- 配置 stdio 传输

### Step 4: 配置管理 (`config.py`)
- 从环境变量或配置常量读取 API Key 和 Base URL
- 默认值:
  - `ANYTHINGLLM_BASE_URL = "http://localhost:3001/api/v1"`
  - `ANYTHINGLLM_API_KEY` 必须通过环境变量设置

### Step 5: 测试与验证
- 启动 MCP Server
- 使用 `mcp dev` 或 `Client(server)` 进行内测
- 验证 `query_workspace` 工具能正确调用 AnythingLLM 并返回回答

## 关键代码参考

### MCP Server 2026-07-28 模板
```python
from mcp.server import MCPServer
from mcp.types import Tool, TextContent

mcp = MCPServer("anythingllm")

@mcp.tool()
async def query_workspace(question: str, workspace_slug: str) -> str:
    """从指定工作区的文档中提取信息并生成AI回答。"""
    ...
```

### stdio 启动方式
```python
from mcp.server import MCPServer
import asyncio

async def main():
    async with mcp.run(transport="stdio") as:
        pass
```

或使用 `mcp dev server.py` 命令启动。

## 风险与注意事项
1. AnythingLLM 的 stream-chat 返回 SSE 格式，需要正确解析
2. 2026-07-28 协议无握手，`MCPServer` 自动处理
3. `mcp` 包 v2.x 的类型系统使用 snake_case
4. 工具参数无需 JSON Schema，类型提示即为 schema
5. 同步函数会自动运行在工作线程，不阻塞事件循环

## 后续扩展方向（不在 MVP 范围）
- 多工作区支持
- 向量搜索工具
- 文档上传管理
- 资源暴露（暴露文档列表为 resource）
- Prompt 模板
- Streamable HTTP 传输
- 认证缓存和刷新
