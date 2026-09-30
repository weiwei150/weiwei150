# AGENTS.md - 开发指南

## 后续开发命令

### 安装依赖
```bash
python -m pip install -e "D:/weiLLM/anythingllm-mcp-server"
```

### 启动 MCP Server
```bash
python -m anythingllm_mcp.server
# 或
anythingllm-mcp
```

### 测试工具调用
```bash
python -c "
import sys, asyncio
sys.path.insert(0, r'D:\weiLLM\anythingllm-mcp-server\src')
from anythingllm_mcp.server import mcp
result = asyncio.run(mcp.list_tools())
print([t.name for t in result])
"
```

### 使用 MCP Inspector
```bash
uv run mcp dev src/anythingllm_mcp/server.py
```

### 运行测试
```bash
python -m pytest tests/
```

## 关键代码位置

- **MCP Server**: `src/anythingllm_mcp/server.py` - `MCPServer("anythingllm")` + `@mcp.tool()` 装饰器
- **AnythingLLM 客户端**: `src/anythingllm_mcp/anythingllm.py` - `AnythingLLMClient` 类
- **配置**: `src/anythingllm_mcp/config.py` - API URL 和 Key
- **入口**: `src/anythingllm_mcp/__init__.py`

## 协议要点 (2026-07-28)

- `MCPServer` 替代 `FastMCP`
- `@mcp.tool()` 装饰器注册工具
- `mcp.run(transport="stdio")` 同步启动
- 类型提示即为 JSON Schema
- 无握手、无会话
- `Client(mode="2026-07-28")` 连接

## 扩展方向

- 添加 `list_workspaces` 工具
- 添加 `vector_search` 工具
- 暴露文档列表为 resource
- 添加 prompt 模板
- 支持 streamable-http 传输
