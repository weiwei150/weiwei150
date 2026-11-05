"""xagent 核心层。

UI 层只需要从这里导入公共 API。
"""

from .agent import AgentSession
from .config import ConfigError, Settings, load_settings
from .events import (
    AgentEvent,
    RunFailed,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
)
from .factory import create_session
from .llm import ChatModel, LLMDelta, OpenAIChatModel, ToolCallDelta
from .models import ToolCall, ToolExecution
from .skills import (
    Skill,
    SkillRegistry,
    build_skills_prompt,
    discover_skills,
    parse_frontmatter,
)
from .tools import Tool, ToolContext, ToolRegistry, build_default_registry

__all__ = [
    "AgentEvent",
    "AgentSession",
    "ChatModel",
    "ConfigError",
    "LLMDelta",
    "OpenAIChatModel",
    "RunFailed",
    "RunFinished",
    "RunStarted",
    "Settings",
    "Skill",
    "SkillRegistry",
    "TextDelta",
    "Tool",
    "ToolCall",
    "ToolCallDelta",
    "ToolCallFinished",
    "ToolCallStarted",
    "ToolContext",
    "ToolExecution",
    "ToolRegistry",
    "build_default_registry",
    "build_skills_prompt",
    "create_session",
    "discover_skills",
    "load_settings",
    "parse_frontmatter",
]
