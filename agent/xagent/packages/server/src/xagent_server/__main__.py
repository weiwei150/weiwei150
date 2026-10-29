"""Web 启动入口：``python -m xagent_server``。"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from collections.abc import Sequence
from contextlib import suppress

from xagent_core.config import ConfigError, load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xagent-web",
        description="xagent - 本地文件操作 Agent（Web UI）",
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
        "--host",
        default="127.0.0.1",
        help="监听地址，默认 127.0.0.1（仅本机访问）",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8000,
        help="监听端口，默认 8000",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="启动后不自动打开浏览器",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="uvicorn 日志级别，默认 info",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="xagent 0.2.0",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not 1 <= args.port <= 65535:
        print("端口必须在 1-65535 之间", file=sys.stderr)
        return 2

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    from .app import create_app

    app = create_app(settings=settings, base_dir=args.directory)

    display_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{display_host}:{args.port}"
    print(f"xagent web 已启动: {url}")
    print("按 Ctrl+C 停止。若浏览器未自动打开，请手动访问上面的地址。")

    if not args.no_open:
        timer = threading.Timer(1.0, _open_browser, args=[url])
        timer.daemon = True
        timer.start()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


def _open_browser(url: str) -> None:
    with suppress(Exception):
        webbrowser.open(url)


if __name__ == "__main__":
    raise SystemExit(main())
