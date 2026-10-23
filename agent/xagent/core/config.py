"""配置加载。

配置来源优先级：命令行显式路径 > 环境变量 XAGENT_CONFIG > 项目根目录 config.ini。
单项配置也可以通过环境变量覆盖，便于部署到不同环境。
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.ini"

DEFAULT_MAX_READ_CHARS = 20_000
DEFAULT_MAX_TOOL_ROUNDS = 16


class ConfigError(RuntimeError):
    """配置缺失或非法时抛出。"""


@dataclass(frozen=True)
class Settings:
    """运行 Agent 所需的全部配置。"""

    base_url: str
    model_name: str
    api_key: str
    max_read_chars: int = DEFAULT_MAX_READ_CHARS
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    config_path: Path | None = None


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def load_settings(config_path: str | Path | None = None) -> Settings:
    """读取并校验配置。

    找不到配置文件时抛出 ``ConfigError``，而不是在后续代码里产生难懂的
    ``KeyError``。
    """

    explicit_path = config_path or os.environ.get("XAGENT_CONFIG")
    if explicit_path:
        path = Path(explicit_path).expanduser()
    elif DEFAULT_CONFIG_PATH.is_file():
        path = DEFAULT_CONFIG_PATH
    else:
        # 安装到 site-packages 等场景下，回退到启动目录
        path = Path.cwd() / "config.ini"
    path = path.resolve()

    parser = configparser.ConfigParser()
    if not path.is_file():
        raise ConfigError(
            f"未找到配置文件: {path}\n"
            "请复制 config.ini.example 为 config.ini 并填写 [llm] 配置，"
            "或通过 XAGENT_CONFIG 指定配置文件路径。"
        )
    if not parser.read(path, encoding="utf-8"):
        raise ConfigError(f"无法读取配置文件: {path}")
    if not parser.has_section("llm"):
        raise ConfigError(f"配置文件缺少 [llm] 段: {path}")

    base_url = (_first_env("XAGENT_BASE_URL") or parser.get("llm", "base_url", fallback="")).strip()
    model_name = (_first_env("XAGENT_MODEL", "XAGENT_MODEL_NAME") or parser.get("llm", "model_name", fallback="")).strip()
    api_key = (_first_env("XAGENT_API_KEY") or parser.get("llm", "api_key", fallback="")).strip()

    missing = [
        name
        for name, value in (
            ("base_url", base_url),
            ("model_name", model_name),
            ("api_key", api_key),
        )
        if not value
    ]
    if missing:
        raise ConfigError(f"配置项为空: {', '.join(missing)}（配置文件: {path}）")

    max_read_chars = parser.getint("agent", "max_read_chars", fallback=DEFAULT_MAX_READ_CHARS)
    max_tool_rounds = parser.getint("agent", "max_tool_rounds", fallback=DEFAULT_MAX_TOOL_ROUNDS)
    if max_read_chars <= 0:
        raise ConfigError("agent.max_read_chars 必须是正整数")
    if max_tool_rounds <= 0:
        raise ConfigError("agent.max_tool_rounds 必须是正整数")

    return Settings(
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        max_read_chars=max_read_chars,
        max_tool_rounds=max_tool_rounds,
        config_path=path,
    )
