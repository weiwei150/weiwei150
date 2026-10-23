"""统一启动入口。

当前只提供 TUI。未来新增 Web / Desktop 时，在这里按 ``--ui`` 选择对应前端，
而 ``core`` 不需要任何改动。
"""

from __future__ import annotations

from tui.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
