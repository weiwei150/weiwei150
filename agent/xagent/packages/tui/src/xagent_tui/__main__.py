"""TUI 启动入口：``python -m xagent_tui``。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from xagent_core.config import ConfigError, load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xagent",
        description="xagent - 本地文件操作 Agent（Textual TUI）",
    )
    parser.add_argument(
        "-c",
        "--config",
        help="配置文件路径，默认读取项目根目录的 config.ini",
    )
    parser.add_argument(
        "-d",
        "--directory",
        help="工具的工作目录，默认为启动命令时的当前目录",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="xagent 0.2.0",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    from .app import XAgentApp

    XAgentApp(settings=settings, base_dir=args.directory).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
