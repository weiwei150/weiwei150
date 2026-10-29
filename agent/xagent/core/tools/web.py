"""网页抓取工具。

先用 ``subprocess`` 调用本地 ``curl`` 获取 HTML 源码，再用 ``trafilatura``
提取正文并转换为 Markdown，最后把原始 URL 和 Markdown 一起返回给模型。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import trafilatura

from .base import Tool, ToolContext
from .curl import DEFAULT_TIMEOUT, MAX_TIMEOUT, request
from .helpers import fail, ok, positive_int

MAX_CHARS_LIMIT = 200_000
DEFAULT_MAX_CHARS = 20_000

# 常见二进制文件头，避免把 PDF / 图片等交给 HTML 解析器
BINARY_SIGNATURES = (
    b"%PDF",
    b"\x89PNG",
    b"\xff\xd8\xff",
    b"GIF8",
    b"PK\x03\x04",
    b"\x1f\x8b",
)


def _clean_markdown(text: str) -> str:
    """清理 Markdown 中的噪声，进一步减少上下文 token。

    保留标题、段落、列表、表格和链接，只移除标题后的 ``[¶]`` 永久链接、
    空链接、行尾空白和连续空行。
    """

    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = re.sub(r"\s*\[(?:¶|#|🔗)\]\([^)]*\)", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[\]\([^)]*\)", "", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_markdown(html: bytes | str, url: str | None = None) -> str | None:
    """使用 trafilatura 提取正文并转换为 Markdown。

    ``include_formatting`` / ``include_tables`` / ``include_links`` 保证标题、
    列表、表格和链接被保留；trafilatura 的正文识别负责去掉导航、广告和页脚。
    """

    def extract(*, favor_recall: bool) -> str | None:
        return trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            include_links=True,
            include_formatting=True,
            include_images=False,
            favor_recall=favor_recall,
            deduplicate=True,
        )

    # 默认使用平衡模式，优先保证正文干净；极简页面容易被判定为无正文，
    # 此时再用召回模式重试，避免误丢内容。
    markdown = extract(favor_recall=False)
    if not markdown or len(markdown) < 200:
        fallback = extract(favor_recall=True)
        if fallback and len(fallback) > len(markdown or ""):
            markdown = fallback

    if not markdown:
        return None
    return _clean_markdown(markdown)


def _normalize_url(raw: object) -> tuple[str | None, str | None]:
    """补全协议并校验，返回 (URL, 错误信息)。"""

    url = str(raw or "").strip()
    if not url:
        return None, "url 不能为空"
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        scheme = urlsplit(url).scheme.lower()
        if scheme not in {"http", "https"}:
            return None, "仅支持 http/https 协议"
        if not urlsplit(url).netloc:
            return None, "url 缺少主机名"
        return url, None
    if url.startswith("//"):
        return "https:" + url, None
    return "https://" + url, None


def fetch_web_page(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    """获取网页 HTML，转换成 Markdown 后返回。"""

    url, error = _normalize_url(arguments.get("url"))
    if error is not None:
        return fail(error)

    max_chars = positive_int(
        arguments.get("max_chars"),
        context.max_read_chars or DEFAULT_MAX_CHARS,
        MAX_CHARS_LIMIT,
    )
    timeout = positive_int(arguments.get("timeout"), DEFAULT_TIMEOUT, MAX_TIMEOUT)

    response = request(url or "", timeout)
    if response.error is not None:
        return fail(response.error, url=url)

    raw = response.data
    if b"\x00" in raw[:8192] or raw.startswith(BINARY_SIGNATURES):
        return fail("网页返回的是二进制内容，无法提取正文", url=url)

    try:
        markdown = extract_markdown(raw, url=url)
    except Exception as exc:  # noqa: BLE001 - 解析失败不能中断会话
        error_name = type(exc).__name__
        if "Parser" in error_name or "XML" in error_name:
            return fail(f"HTML 解析失败: {error_name}: {exc}", url=url)
        return fail(f"提取网页正文失败: {error_name}: {exc}", url=url)

    if not markdown or not markdown.strip():
        return fail(
            "无法从该网页提取正文，可能不是 HTML 页面或内容由 JavaScript 动态生成",
            url=url,
        )

    content = markdown.strip()
    total_chars = len(content)
    truncated = total_chars > max_chars

    return ok(
        url=url,
        markdown=content[:max_chars],
        total_chars=total_chars,
        truncated=truncated,
    )


def build_web_tools() -> list[Tool]:
    return [
        Tool(
            name="fet",
            description=(
                "获取指定网页的主要内容。通过本地 curl 下载网页 HTML，"
                "再用 trafilatura 提取正文并转换为 Markdown，保留标题、段落、"
                "列表、表格和链接，去除导航栏、广告、页脚等无关内容，"
                "返回原始 URL 和 Markdown 正文。支持 http/https 链接"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "网页地址，可省略 https:// 前缀",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": (
                            "返回 Markdown 的最大字符数，"
                            "默认使用配置中的 max_read_chars"
                            f"（上限 {MAX_CHARS_LIMIT}）"
                        ),
                    },
                    "timeout": {
                        "type": "integer",
                        "description": f"请求超时秒数，默认 {DEFAULT_TIMEOUT}，最大 {MAX_TIMEOUT}",
                    },
                },
                "required": ["url"],
            },
            handler=fetch_web_page,
        )
    ]
