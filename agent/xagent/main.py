"""统一启动入口。

默认启动 Textual TUI；使用 ``--ui web`` 启动浏览器前端。
两个前端都复用同一个 ``core``。
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
        from web.__main__ import main as web_main

        return web_main(args)
    if ui == "tui":
        from tui.__main__ import main as tui_main

        return tui_main(args)

    print(f"未知 UI: {ui}（可选 tui / web）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
