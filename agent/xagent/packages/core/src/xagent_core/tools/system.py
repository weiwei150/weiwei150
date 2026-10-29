"""时间查询工具。"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .base import Tool, ToolContext
from .helpers import ok


def get_date(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    """优先使用 Windows 系统命令，其他平台回退到 Python 时间。"""

    if os.name == "nt":
        result = subprocess.run(
            "date /t & time /t",
            shell=True,
            check=False,
            capture_output=True,
            text=True,
        )
        output = result.stdout.strip()
        if output:
            return ok(datetime=output, source="system-command")

    now = datetime.now().astimezone()
    return ok(
        datetime=now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        source="python",
    )


def build_system_tools() -> list[Tool]:
    return [
        Tool(
            name="get_date",
            description="获取当前电脑的日期和时间",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=get_date,
        )
    ]
