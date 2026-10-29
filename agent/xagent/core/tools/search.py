"""网络搜索工具。

调用百度千帆「百度搜索」API（``/v2/ai_search/web_search``），返回搜索摘要
以及参考来源的标题和 URL，供模型判断哪些结果值得进一步用 ``fet`` 打开。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from .base import Tool, ToolContext
from .curl import DEFAULT_TIMEOUT, MAX_TIMEOUT, request
from .helpers import fail, ok, positive_int

DEFAULT_MAX_RESULTS = 5
MAX_RESULTS_LIMIT = 10
MAX_SNIPPET_CHARS = 600

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_HTTP_STATUS_RE = re.compile(r"returned error:\s*(\d{3})", re.IGNORECASE)

_HTTP_STATUS_HINTS = {
    401: "鉴权失败，请检查 [search] baidu_qianfan_api_key 是否正确",
    403: "无访问权限或账户额度不足，请检查千帆控制台",
    404: "接口地址不存在，请检查 [search] endpoint 配置",
    429: "请求过于频繁或额度耗尽，请稍后重试",
    500: "千帆服务端错误，请稍后重试",
    502: "千帆服务网关错误，请稍后重试",
    503: "千帆服务暂时不可用，请稍后重试",
}


class SearchResponseError(RuntimeError):
    """搜索 API 返回格式不符合预期。"""


class SearchAPIError(RuntimeError):
    """搜索 API 返回了业务错误码。"""

    def __init__(
        self,
        code: object,
        message: str,
        request_id: str | None = None,
    ) -> None:
        super().__init__(f"千帆搜索 API 返回错误（code={code}）: {message}")
        self.code = code
        self.message = message
        self.request_id = request_id


def _clean_text(value: object, limit: int | None = None) -> str:
    text = _CONTROL_RE.sub(" ", str(value or ""))
    text = " ".join(text.split())
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def build_search_payload(
    query: str,
    max_results: int,
    *,
    edition: str = "standard",
) -> dict[str, Any]:
    """构造千帆百度搜索 API 的请求体。"""

    return {
        "messages": [{"role": "user", "content": query}],
        "search_source": "baidu_search_v2",
        "edition": edition,
        "resource_type_filter": [{"type": "web", "top_k": max_results}],
    }


def parse_search_response(raw: bytes, limit: int) -> tuple[list[dict[str, str]], str | None]:
    """解析 API 响应，返回 (结果列表, request_id)。"""

    try:
        data = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise SearchResponseError(f"搜索 API 返回了非法 JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise SearchResponseError("搜索 API 返回的不是 JSON 对象")

    request_id = str(data.get("request_id") or data.get("requestId") or "") or None

    code = data.get("code")
    if code not in (None, 0, "0"):
        message = _clean_text(data.get("message")) or "未知错误"
        raise SearchAPIError(code, message, request_id)

    references = data.get("references")
    if not isinstance(references, list):
        raise SearchResponseError("搜索 API 响应中缺少 references 字段")

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for reference in references:
        if not isinstance(reference, dict):
            continue

        title = _clean_text(reference.get("title")) or _clean_text(
            reference.get("web_anchor")
        )
        url = str(reference.get("url") or "").strip()
        if not title or not url:
            continue
        if urlsplit(url).scheme.lower() not in {"http", "https"}:
            continue
        if url in seen:
            continue

        item = {
            "title": title,
            "url": url,
            "snippet": _clean_text(
                reference.get("content"),
                limit=MAX_SNIPPET_CHARS,
            ),
        }
        date = _clean_text(reference.get("date"))
        if date:
            item["date"] = date

        seen.add(url)
        results.append(item)
        if len(results) >= limit:
            break

    return results, request_id


def _classify_network_error(error: str) -> tuple[str, str]:
    """把 curl / HTTP 错误转换为原因类型和面向模型的提示。"""

    match = _HTTP_STATUS_RE.search(error)
    if match:
        status = int(match.group(1))
        hint = _HTTP_STATUS_HINTS.get(status, "请稍后重试或检查接口配置")
        message = f"搜索接口返回 HTTP {status}：{hint}"
        if status in {401, 403}:
            return "auth_error", message
        if status == 429:
            return "rate_limited", message
        return "network_error", message

    if "超时" in error:
        return "timeout", f"搜索请求超时：{error}"
    if "无法解析主机名" in error or "无法连接到目标服务器" in error:
        return "network_error", f"无法连接搜索服务：{error}"
    return "network_error", f"搜索请求失败：{error}"


def _api_error_hint(api_error: SearchAPIError) -> str:
    """根据千帆错误码 / 错误消息补充排查建议。"""

    code = str(api_error.code)
    message = api_error.message.lower()
    if code == "216003" or "auth" in message or "apikey" in message:
        return "；请检查 [search] baidu_qianfan_api_key 是否正确"
    if "quota" in message or "balance" in message or "limit" in message:
        return "；请检查千帆账户余额或调用额度"
    if "timeout" in message:
        return "；请稍后重试或调大 timeout 参数"
    return ""


def search_web(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    """调用千帆搜索 API 并返回摘要与来源。"""

    query = " ".join(str(arguments.get("query", "")).split())
    if not query:
        return fail("query 不能为空", reason="invalid_argument")

    if not context.search_api_key:
        return fail(
            "未配置千帆搜索 API Key。请在 config.ini 的 [search] 段填写 "
            "baidu_qianfan_api_key，或设置环境变量 XAGENT_QIANFAN_API_KEY",
            query=query,
            reason="missing_config",
        )

    default_results = (
        context.search_top_k
        if 1 <= context.search_top_k <= MAX_RESULTS_LIMIT
        else DEFAULT_MAX_RESULTS
    )
    max_results = positive_int(
        arguments.get("max_results"),
        default_results,
        MAX_RESULTS_LIMIT,
    )
    timeout = positive_int(arguments.get("timeout"), DEFAULT_TIMEOUT, MAX_TIMEOUT)

    payload = build_search_payload(query, max_results)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    response = request(
        context.search_endpoint,
        timeout,
        accept="application/json",
        extra_headers=(f"Authorization: Bearer {context.search_api_key}",),
        body=body,
    )
    if response.error is not None:
        reason, message = _classify_network_error(response.error)
        return fail(
            message,
            query=query,
            reason=reason,
        )

    try:
        results, request_id = parse_search_response(response.data, max_results)
    except SearchAPIError as exc:
        extra: dict[str, Any] = {
            "query": query,
            "reason": "api_error",
            "api_code": exc.code,
        }
        if exc.request_id:
            extra["request_id"] = exc.request_id
        return fail(
            f"{exc}{_api_error_hint(exc)}",
            **extra,
        )
    except SearchResponseError as exc:
        return fail(
            f"搜索接口返回内容异常：{exc}",
            query=query,
            reason="invalid_response",
        )

    if not results:
        return fail(
            "搜索成功，但没有返回可用的网页结果，请尝试更换关键词或稍后重试",
            query=query,
            reason="no_results",
        )

    response_payload: dict[str, Any] = {
        "query": query,
        "engine": "baidu-qianfan",
        "count": len(results),
        "results": results,
    }
    if request_id:
        response_payload["request_id"] = request_id
    return ok(**response_payload)


def build_search_tools() -> list[Tool]:
    return [
        Tool(
            name="searchweb",
            description=(
                "调用百度千帆搜索 API 获取互联网最新信息，返回搜索结果摘要、"
                "参考来源的标题和 URL。适合先搜索，需要详细内容时再调用 fet"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "返回结果数量，默认使用配置中的 search.top_k，"
                            f"最大 {MAX_RESULTS_LIMIT}"
                        ),
                    },
                    "timeout": {
                        "type": "integer",
                        "description": f"请求超时秒数，默认 {DEFAULT_TIMEOUT}，最大 {MAX_TIMEOUT}",
                    },
                },
                "required": ["query"],
            },
            handler=search_web,
        )
    ]
