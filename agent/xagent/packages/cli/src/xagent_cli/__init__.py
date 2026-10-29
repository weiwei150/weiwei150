"""xagent 统一命令行入口。

``xagent`` 默认启动 TUI；``xagent --ui web`` 启动 Web 服务。
"""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    ui = "tui"

    for index, argument in enumerate(args):
        if argument == "--ui":
            if index + 1 >= len(args):
                print("--ui 需要一个值：tui 或 web", file=sys.stderr)
                return 2
            ui = args[index + 1]
            del args[index : index + 2]
            break
        if argument.startswith("--ui="):
            ui = argument.split("=", 1)[1]
            del args[index]
            break

    if ui == "web":
        from xagent_server.__main__ import main as web_main

        return web_main(args)
    if ui == "tui":
        from xagent_tui.__main__ import main as tui_main

        return tui_main(args)

    print(f"未知 UI: {ui}（可选 tui / web）", file=sys.stderr)
    return 2


__all__ = ["main"]
