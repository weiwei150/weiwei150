# chat.py

一个最简的 Python 命令行聊天脚本，通过 OpenAI 兼容接口调用大语言模型，并以打字机效果流式输出结果。

## 环境要求

- Python 3.8+
- 一个 OpenAI 兼容接口的 `base_url`、`model_name` 和 `api_key`

## 安装

```bash
pip install -r requirements.txt
```

## 配置

在同目录下创建 `config.ini`，三项配置放在 `[llm]` 段落下：

```ini
[llm]
base_url = https://api.deepseek.com
model_name = deepseek-chat
api_key = sk-your-key-here
```

| 配置项 | 说明 |
| --- | --- |
| `base_url` | 接口地址，需兼容 OpenAI SDK |
| `model_name` | 模型名称，如 `deepseek-chat`、`deepseek-reasoner` |
| `api_key` | 访问密钥 |

建议把 `config.ini` 加入 `.gitignore`，避免密钥被提交到仓库。

## 使用

```bash
python chat.py
```

运行后按提示输入内容并回车，例如：

```
请输入提示词: 什么是晴天
---
晴天指天空万里无云或云量极少的天气...
```

输入 `exit`、`quit` 或 `退出` 结束程序。

## 原理

脚本顺序执行四步：读取 `config.ini` → 等待输入提示词 → 打印 `---` 分隔线 → 以 `stream=True` 调用 `chat.completions.create`，遍历每个 chunk 取出 `delta.content`，用 `print(..., end='', flush=True)` 逐块输出，最后补一个换行。

## 常见问题

**`ModuleNotFoundError: No module named 'openai'`**
执行 `pip install -r requirements.txt`。

**`Error code: 401`**
`api_key` 无效或已过期。

**`Error code: 402 Insufficient Balance`**
账户余额不足，需要前往服务商平台充值。

**`Error code: 404` / 模型不存在**
`model_name` 与 `base_url` 不匹配。`https://api.deepseek.com` 官方仅提供 `deepseek-chat` 和 `deepseek-reasoner`；若使用第三方中转服务，请确认对应的模型名。
