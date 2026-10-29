"""统一启动入口。

默认启动 Textual TUI；使用 ``--ui web`` 启动浏览器前端。
未安装为包时，本文件会把 ``packages/*/src`` 加入 ``sys.path``。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for package in ("core", "server", "tui", "cli"):
    source = ROOT / "packages" / package / "src"
    if source.is_dir() and str(source) not in sys.path:
        sys.path.insert(0, str(source))

from xagent_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
