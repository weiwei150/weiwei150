"""本地 curl 调用封装。

所有网络工具都通过参数列表调用 curl，显式 ``shell=False``，统一处理
超时、退出码、空响应等异常，避免各工具重复实现。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_TIMEOUT = 15
MAX_TIMEOUT = 60
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 xagent/0.1"
)

CURL_ERROR_MESSAGES = {
    6: "无法解析主机名",
    7: "无法连接到目标服务器",
    22: "网页访问失败（HTTP 错误状态码）",
    28: "请求超时",
    35: "TLS 握手失败",
    47: "重定向次数过多",
    52: "服务器返回了空响应",
    63: "网页内容超过大小限制",
}


@dataclass(frozen=True)
class CurlResponse:
    """一次 curl 请求的结果。"""

    data: bytes = b""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def find_curl() -> str | None:
    """查找本地 curl 可执行文件。"""

    for name in ("curl.exe", "curl"):
        path = shutil.which(name)
        if path:
            return path
    return None


def build_curl_command(
    curl: str,
    url: str,
    timeout: int,
    *,
    accept: str = "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    extra_headers: tuple[str, ...] = (),
    body: bytes | None = None,
) -> list[str]:
    """构造网络请求命令，URL 和请求体都通过参数列表 / stdin 传递。"""

    command = [
        curl,
        "--location",
        "--fail",
        "--compressed",
        "--silent",
        "--show-error",
        "--max-time",
        str(timeout),
        "--max-filesize",
        str(MAX_DOWNLOAD_BYTES),
        "--max-redirs",
        "5",
        "--proto",
        "=http,https",
        "--proto-redir",
        "=http,https",
        "--user-agent",
        USER_AGENT,
        "--header",
        f"Accept: {accept}",
        "--header",
        "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
    ]
    for header in extra_headers:
        command.extend(["--header", header])
    if body is not None:
        command.extend([
            "--request",
            "POST",
            "--header",
            "Content-Type: application/json",
            "--data-binary",
            "@-",
        ])
    command.append(url)
    return command


def request(
    url: str,
    timeout: int,
    *,
    accept: str = "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    extra_headers: tuple[str, ...] = (),
    body: bytes | None = None,
) -> CurlResponse:
    """调用 curl 获取网页内容，所有异常都转换为 ``CurlResponse.error``。"""

    curl = find_curl()
    if curl is None:
        return CurlResponse(error="未找到本地 curl 程序，请确认 curl 已安装并在 PATH 中")

    command = build_curl_command(
        curl,
        url,
        timeout,
        accept=accept,
        extra_headers=extra_headers,
        body=body,
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    stdin_options = (
        {"input": body} if body is not None else {"stdin": subprocess.DEVNULL}
    )

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout + 5,
            check=False,
            # 显式关闭 shell，参数以列表形式直接传给 curl，避免命令注入
            shell=False,
            creationflags=creationflags,
            **stdin_options,
        )
    except subprocess.TimeoutExpired:
        return CurlResponse(error=f"请求超时（超过 {timeout} 秒）")
    except subprocess.SubprocessError as exc:
        return CurlResponse(error=f"调用 curl 失败: {type(exc).__name__}: {exc}")
    except (OSError, ValueError) as exc:
        return CurlResponse(error=f"调用 curl 失败: {exc}")

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        message = CURL_ERROR_MESSAGES.get(
            result.returncode,
            f"网页访问失败（curl 退出码 {result.returncode}）",
        )
        if stderr:
            message = f"{message}: {stderr}"
        return CurlResponse(error=message)

    if not result.stdout:
        return CurlResponse(error="网页返回了空内容")

    return CurlResponse(data=result.stdout)
