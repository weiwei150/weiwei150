"""本地命令行工具。

通过 ``subprocess`` 以参数列表方式执行已安装的 CLI 程序（显式
``shell=False``），并把退出码、stdout、stderr 返回给模型。

只允许执行配置文件 ``[agent] allowed_commands`` 中列出的程序名；未配置时
默认拒绝所有命令。白名单限制程序名，不构成操作系统级安全沙箱。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .base import Tool, ToolContext
from .helpers import fail, ok, positive_int, resolve_path

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 300
MAX_OUTPUT_LIMIT = 100_000
MAX_STDERR_CHARS = 10_000


def _decode_output(raw: bytes) -> str:
    """兼容 Windows 常见的 UTF-8 / GB18030 输出编码。"""

    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _truncate(text: str, limit: int) -> tuple[str, bool, int]:
    """截断输出，返回 (文本, 是否截断, 截断前字符数)。"""

    text = text.rstrip()
    total = len(text)
    if total <= limit:
        return text, False, total
    return text[:limit], True, total


def _resolve_executable(command: str, cwd: Path) -> Path | None:
    """解析可执行文件：支持 PATH 中的命令名和显式路径。"""

    candidate = Path(os.path.expandvars(os.path.expanduser(command)))
    looks_like_path = (
        candidate.is_absolute()
        or "/" in command
        or "\\" in command
        or candidate.suffix.lower() in {".exe", ".com", ".cmd", ".bat"}
    )

    if looks_like_path:
        path = candidate if candidate.is_absolute() else cwd / candidate
        path = path.resolve()
        if path.is_file():
            return path
        # 只写了程序名（如 git.exe）时继续到 PATH 中查找
        if candidate.is_absolute() or "/" in command or "\\" in command:
            return None

    found = shutil.which(command)
    return Path(found) if found else None


def _string_args(raw: object) -> list[str] | None:
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        return None
    return [str(item) for item in raw]


def _command_key(command: str) -> str:
    """按可执行文件名匹配白名单，兼容 Windows 路径和扩展名。"""

    return Path(command.replace("\\", "/")).stem.casefold()


def run_cli(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    """执行本地命令行程序。"""

    command = str(arguments.get("command", "")).strip()
    if not command:
        return fail("command 不能为空")

    args = _string_args(arguments.get("args"))
    if args is None:
        return fail("args 必须是字符串数组，例如 [\"--version\"]")

    allowed_commands = {_command_key(item) for item in context.allowed_commands}
    command_key = _command_key(command)
    if not allowed_commands:
        return fail("Runcli 命令白名单为空；请在 [agent] allowed_commands 中配置允许的程序名")
    if command_key not in allowed_commands:
        return fail(
            f"命令不在 Runcli 白名单中: {command}",
            allowed_commands=sorted(allowed_commands),
        )

    try:
        cwd = resolve_path(context, arguments.get("cwd", "."))
    except ValueError as exc:
        return fail(f"cwd 无效: {exc}")
    if not cwd.exists():
        return fail("cwd 目录不存在", cwd=str(cwd))
    if not cwd.is_dir():
        return fail("cwd 不是目录", cwd=str(cwd))

    executable = _resolve_executable(command, cwd)
    if executable is None:
        return fail(
            f"未找到可执行程序: {command}。请确认已安装并加入 PATH，或传入完整路径",
            cwd=str(cwd),
        )
    if _command_key(executable.name) not in allowed_commands:
        return fail(
            f"解析后的可执行文件不在 Runcli 白名单中: {executable.name}",
            allowed_commands=sorted(allowed_commands),
            cwd=str(cwd),
        )

    timeout = positive_int(arguments.get("timeout"), DEFAULT_TIMEOUT, MAX_TIMEOUT)
    max_chars = positive_int(
        arguments.get("max_chars"),
        context.max_read_chars,
        MAX_OUTPUT_LIMIT,
    )

    stdin_text = arguments.get("stdin")
    input_bytes = None if stdin_text is None else str(stdin_text).encode("utf-8")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    # 程序名和参数组装成列表，直接传给 subprocess，不拼接 shell 字符串
    command_args = [str(executable), *args]

    try:
        completed = subprocess.run(
            command_args,
            capture_output=True,
            timeout=timeout,
            check=False,
            cwd=str(cwd),
            # 显式关闭 shell，参数以列表形式直接传给程序，避免命令注入
            shell=False,
            creationflags=creationflags,
            input=input_bytes,
            stdin=subprocess.DEVNULL if input_bytes is None else None,
        )
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_truncated, stdout_total = _truncate(
            _decode_output(exc.stdout or b""),
            max_chars,
        )
        stderr, stderr_truncated, stderr_total = _truncate(
            _decode_output(exc.stderr or b""),
            MAX_STDERR_CHARS,
        )
        return fail(
            f"命令执行超时（超过 {timeout} 秒），进程已被终止",
            exitcode=None,
            timed_out=True,
            command=command_args,
            cwd=str(cwd),
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            stdout_total_chars=stdout_total,
            stderr_total_chars=stderr_total,
            truncated=stdout_truncated or stderr_truncated,
        )
    except (OSError, ValueError) as exc:
        return fail(
            f"启动命令失败: {type(exc).__name__}: {exc}",
            exitcode=None,
            timed_out=False,
            command=command_args,
            cwd=str(cwd),
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            stdout_total_chars=0,
            stderr_total_chars=0,
            truncated=False,
        )

    stdout, stdout_truncated, stdout_total = _truncate(
        _decode_output(completed.stdout or b""),
        max_chars,
    )
    stderr, stderr_truncated, stderr_total = _truncate(
        _decode_output(completed.stderr or b""),
        MAX_STDERR_CHARS,
    )

    if completed.returncode != 0:
        return fail(
            f"命令执行失败（退出码 {completed.returncode}）",
            exitcode=completed.returncode,
            timed_out=False,
            command=command_args,
            cwd=str(cwd),
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            stdout_total_chars=stdout_total,
            stderr_total_chars=stderr_total,
            truncated=stdout_truncated or stderr_truncated,
        )

    return ok(
        exitcode=0,
        timed_out=False,
        command=command_args,
        cwd=str(cwd),
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        stdout_total_chars=stdout_total,
        stderr_total_chars=stderr_total,
        truncated=stdout_truncated or stderr_truncated,
    )


def build_cli_tools() -> list[Tool]:
    return [
        Tool(
            name="Runcli",
            description=(
                "调用配置文件 [agent] allowed_commands 中列出的本地命令行程序，"
                "返回退出码、标准输出和标准错误。未配置时拒绝所有命令。"
                "command 传白名单中的程序名或完整路径，参数放在 args 字符串数组中；"
                "使用 shell=False，不支持管道、重定向等 shell 语法。"
                "白名单仅限制程序名，不是操作系统级安全沙箱"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "白名单中的程序名（如 git）或该程序的完整路径",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "命令行参数数组，例如 [\"--version\"]",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "工作目录，默认当前工作目录",
                    },
                    "stdin": {
                        "type": "string",
                        "description": "可选的标准输入文本",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": f"超时秒数，默认 {DEFAULT_TIMEOUT}，最大 {MAX_TIMEOUT}",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": (
                            "stdout 最大返回字符数，默认使用配置中的 max_read_chars"
                        ),
                    },
                },
                "required": ["command"],
            },
            handler=run_cli,
        )
    ]
