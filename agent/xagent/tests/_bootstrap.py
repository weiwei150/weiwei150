"""测试引导：让未安装的源码布局也能直接运行测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for package in ("core", "server", "tui", "cli"):
    source = ROOT / "packages" / package / "src"
    if source.is_dir() and str(source) not in sys.path:
        sys.path.insert(0, str(source))
