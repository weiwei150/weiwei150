"""Agent Skills 发现与注册。

项目根目录下 ``.agents/skills/`` 的每个子目录代表一个 skill，至少包含一个
``SKILL.md``（大小写不敏感）。文件开头的 YAML frontmatter 必须声明 ``name``
和 ``description``。

初始化阶段只解析 frontmatter 并保留名称和描述；完整正文只有在模型调用
``loadSkill`` 工具时才会进入对话上下文。
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIRECTORY = Path(".agents") / "skills"
SKILL_FILE_NAME = "skill.md"
SKILL_NAME_MAX_LENGTH = 64
SKILL_DESCRIPTION_MAX_LENGTH = 1024

_FRONTMATTER_DELIMITERS = {"---", "..."}
_KEY_RE = re.compile(r"^([^:#][^:]*?):(?:[ \t]+(.*))?$")
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class Skill:
    """一个已注册的 skill 的元数据。"""

    name: str
    description: str
    directory: Path
    skill_file: Path


class SkillRegistry:
    """保存当前项目发现的 skill，并提供按名称查找。"""

    def __init__(
        self,
        skills: Iterable[Skill] = (),
        *,
        root: Path | None = None,
        warnings: Iterable[str] = (),
    ) -> None:
        ordered = tuple(sorted(skills, key=lambda skill: skill.name.casefold()))
        self._skills = ordered
        self._by_name = {skill.name: skill for skill in ordered}
        self._root = root
        self._warnings = tuple(warnings)

    @property
    def skills(self) -> tuple[Skill, ...]:
        return self._skills

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(skill.name for skill in self._skills)

    @property
    def root(self) -> Path | None:
        """被扫描的 ``.agents/skills`` 目录；未发现时仍可能是预期路径。"""

        return self._root

    @property
    def warnings(self) -> tuple[str, ...]:
        """发现过程中被跳过的目录及原因，供诊断使用（不进入提示词）。"""

        return self._warnings

    def get(self, name: str) -> Skill | None:
        """精确匹配 skill 名称；未命中时再做一次唯一的忽略大小写匹配。"""

        skill = self._by_name.get(name)
        if skill is not None:
            return skill
        matches = [
            item for item in self._skills if item.name.casefold() == name.casefold()
        ]
        return matches[0] if len(matches) == 1 else None

    def register(self, skill: Skill) -> None:
        """把运行时新建的 skill 加入注册表，使其可立即被 loadSkill 加载。"""

        if self.get(skill.name) is not None:
            raise ValueError(f"skill 已存在: {skill.name}")
        self._skills = tuple(
            sorted((*self._skills, skill), key=lambda item: item.name.casefold())
        )
        self._by_name = {item.name: item for item in self._skills}
        if self._root is None:
            self._root = skill.directory.parent

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.get(name) is not None

    def __iter__(self) -> Iterator[Skill]:
        return iter(self._skills)

    def __len__(self) -> int:
        return len(self._skills)

    def __bool__(self) -> bool:
        return bool(self._skills)


def _parse_scalar(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("#"):
        return ""

    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            return str(json.loads(value))
        except (TypeError, ValueError):
            return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")

    # 普通标量中的行内注释只有在 # 前有空白时才是 YAML 注释
    value = re.split(r"[ \t]+#", value, maxsplit=1)[0].rstrip()
    if value in {"~", "null", "Null", "NULL"}:
        return ""
    return value


def _parse_yaml_subset(lines: list[str]) -> dict[str, str]:
    """解析 frontmatter 所需的最小 YAML 子集。

    支持顶层 ``key: value``、单双引号、普通多行标量、``|`` / ``>`` 块标量，
    忽略缩进的嵌套字段和注释。Agent Skills 的 name / description 足以覆盖。
    """

    result: dict[str, str] = {}
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or raw_line[:1] in {" ", "\t"}:
            index += 1
            continue

        match = _KEY_RE.match(raw_line.rstrip())
        if match is None:
            index += 1
            continue

        key = match.group(1).strip()
        value = (match.group(2) or "").strip()
        index += 1

        if value[:1] in {"|", ">"}:
            block: list[str] = []
            while index < len(lines):
                following = lines[index]
                if following.strip() and following[:1] not in {" ", "\t"}:
                    break
                block.append(following)
                index += 1

            indent = min(
                (len(line) - len(line.lstrip(" \t")) for line in block if line.strip()),
                default=0,
            )
            content = [
                line[indent:].rstrip() if len(line) >= indent else line.strip()
                for line in block
            ]
            while content and not content[0].strip():
                content.pop(0)
            while content and not content[-1].strip():
                content.pop()

            if value[0] == "|":
                result[key] = "\n".join(content)
            else:
                result[key] = " ".join(
                    line.strip() for line in content if line.strip()
                )
            continue

        # 普通标量允许在下一行以缩进方式续写
        parts = [value]
        while (
            index < len(lines)
            and lines[index][:1] in {" ", "\t"}
            and lines[index].strip()
            and not lines[index].lstrip().startswith("#")
        ):
            parts.append(lines[index].strip())
            index += 1

        result[key] = _parse_scalar(" ".join(part for part in parts if part))
    return result


def parse_frontmatter(text: str) -> dict[str, str]:
    """从完整文本中提取 frontmatter 字段（没有则返回空字典）。"""

    lines = text.splitlines()
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return {}

    for end in range(1, len(lines)):
        if lines[end].strip() in _FRONTMATTER_DELIMITERS:
            return _parse_yaml_subset(lines[1:end])
    return {}


def normalize_skill_name(raw: object) -> str:
    """把用户提供的名称转换为 Agent Skills 要求的目录名。

    Agent Skills 名称使用小写字母、数字和连字符。空白、下划线、标点以及
    非 ASCII 字符会被折叠为连字符，首尾连字符会被移除。
    """

    text = unicodedata.normalize("NFKC", str(raw if raw is not None else ""))
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def is_valid_skill_name(name: str) -> bool:
    return (
        bool(name)
        and len(name) <= SKILL_NAME_MAX_LENGTH
        and _SKILL_NAME_RE.fullmatch(name) is not None
    )


def split_skill_document(text: str) -> tuple[dict[str, str], str]:
    """分离 SKILL.md 的 frontmatter 和正文。

    没有 frontmatter 时返回空元数据和原文本；frontmatter 缺少结束分隔符时
    抛出 ``ValueError``，避免生成第二个重复的 frontmatter。
    """

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return {}, normalized

    for end in range(1, len(lines)):
        if lines[end].strip() in _FRONTMATTER_DELIMITERS:
            metadata = _parse_yaml_subset(lines[1:end])
            return metadata, "\n".join(lines[end + 1 :])
    raise ValueError("skillContext 的 YAML frontmatter 缺少结束分隔符 ---")


def _derive_description(body: str) -> str:
    """从正文第一段可读文本推导 description。"""

    for line in body.splitlines():
        text = line.strip()
        if not text or text.startswith(("```", "~~~", "<!--")):
            continue
        text = re.sub(r"^#{1,6}\s*", "", text)
        text = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", text)
        text = re.sub(r"[`*_]+", "", text).strip()
        if text:
            return text[:SKILL_DESCRIPTION_MAX_LENGTH].rstrip()
    return ""


def _yaml_scalar(value: str) -> str:
    """输出可读且合法的 YAML 标量；仅在必要时添加双引号。"""

    if not value:
        return '""'
    unsafe_starts = (
        "-", "?", ":", "!", "&", "*", "#", "{", "}", "[", "]",
        ",", "|", ">", "@", "`", '"', "'", "%",
    )
    if (
        value == value.strip()
        and not value.startswith(unsafe_starts)
        and ": " not in value
        and " #" not in value
        and "\n" not in value
    ):
        return value
    return json.dumps(value, ensure_ascii=False)


def compose_skill_document(name: str, skill_context: str) -> tuple[str, str]:
    """生成符合 Agent Skills 规范的 SKILL.md 文本。

    如果 ``skill_context`` 已包含 YAML frontmatter，则复用其中的 description；
    否则从正文首段推导。name 始终以工具参数对应的规范名称为准。
    返回 ``(文档文本, description)``。
    """

    if not isinstance(skill_context, str):
        raise TypeError("skillContext 必须是字符串")
    metadata, body = split_skill_document(skill_context.lstrip("\ufeff"))
    body = body.strip("\n")
    if not body.strip():
        raise ValueError("skillContext 的正文内容不能为空")

    description = " ".join(str(metadata.get("description", "")).split())
    if not description:
        description = _derive_description(body)
    if not description:
        description = f"Instructions for the {name} skill."
    description = " ".join(description.split())[:SKILL_DESCRIPTION_MAX_LENGTH].rstrip()

    frontmatter = (
        "---\n"
        f"name: {name}\n"
        f"description: {_yaml_scalar(description)}\n"
        "---\n\n"
    )
    return f"{frontmatter}{body}\n", description


def _read_frontmatter_text(path: Path) -> str | None:
    """只读取到 frontmatter 结束行为止，不把正文完整载入内存。"""

    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            first = handle.readline()
            if first.lstrip("\ufeff").strip() != "---":
                return None
            collected = [first.rstrip("\r\n")]
            for line in handle:
                cleaned = line.rstrip("\r\n")
                collected.append(cleaned)
                if cleaned.strip() in _FRONTMATTER_DELIMITERS:
                    return "\n".join(collected)
            return None
    except UnicodeDecodeError:
        # 兼容非 UTF-8 的本地文件；只在 UTF-8 解码失败时读入字节
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            return None
        lines = text.splitlines()
        if not lines or lines[0].lstrip("\ufeff").strip() != "---":
            return None
        for end in range(1, len(lines)):
            if lines[end].strip() in _FRONTMATTER_DELIMITERS:
                return "\n".join(lines[: end + 1])
        return None


def read_skill_metadata(path: Path) -> dict[str, str]:
    """读取 ``SKILL.md`` 的 frontmatter，不保留正文。"""

    frontmatter = _read_frontmatter_text(path)
    if frontmatter is None:
        return {}
    return parse_frontmatter(frontmatter)


def _find_skill_file(directory: Path) -> Path | None:
    """查找 skill 子目录直属的 SKILL.md（大小写不敏感）。"""

    exact = directory / "SKILL.md"
    if exact.is_file():
        return exact
    try:
        matches = sorted(
            (
                child
                for child in directory.iterdir()
                if child.is_file() and child.name.casefold() == SKILL_FILE_NAME
            ),
            key=lambda item: item.name,
        )
    except OSError:
        return None
    return matches[0] if matches else None


def discover_skills(project_root: str | Path) -> SkillRegistry:
    """扫描 ``<project_root>/.agents/skills``，注册所有合法 skill。

    只保留 frontmatter 中的 name 和 description；正文不进入注册表。
    非法目录会被跳过，原因记录在 ``SkillRegistry.warnings``。
    """

    root = Path(project_root).expanduser().resolve()
    skills_root = root / SKILLS_DIRECTORY
    warnings: list[str] = []

    if not skills_root.is_dir():
        return SkillRegistry(root=skills_root, warnings=())

    try:
        children = sorted(skills_root.iterdir(), key=lambda item: item.name.casefold())
    except OSError as exc:
        return SkillRegistry(
            root=skills_root,
            warnings=[f"无法读取 skills 目录 {skills_root}: {exc}"],
        )

    skills: list[Skill] = []
    seen: set[str] = set()

    for directory in children:
        if not directory.is_dir():
            continue

        skill_file = _find_skill_file(directory)
        if skill_file is None:
            warnings.append(f"跳过 {directory.name}: 缺少 SKILL.md")
            continue

        try:
            metadata = read_skill_metadata(skill_file)
        except OSError as exc:
            warnings.append(f"跳过 {directory.name}: 无法读取 SKILL.md ({exc})")
            continue

        name = str(metadata.get("name", "")).strip()
        description = str(metadata.get("description", "")).strip()
        if not name:
            warnings.append(f"跳过 {directory.name}: frontmatter 缺少 name")
            continue
        if not description:
            warnings.append(f"跳过 {directory.name}: frontmatter 缺少 description")
            continue
        if name in seen:
            warnings.append(f"跳过 {directory.name}: skill 名称重复 ({name})")
            continue

        seen.add(name)
        skills.append(
            Skill(
                name=name,
                description=description,
                directory=directory.resolve(),
                skill_file=skill_file.resolve(),
            )
        )

    return SkillRegistry(skills, root=skills_root, warnings=warnings)


def build_skills_prompt(skills: SkillRegistry | Iterable[Skill]) -> str:
    """生成注入 system prompt 的 skill 清单；没有 skill 时返回空字符串。"""

    items = skills.skills if isinstance(skills, SkillRegistry) else tuple(skills)
    if not items:
        return ""

    lines = ["You have access to the following skills:"]
    for skill in items:
        description = " ".join(skill.description.split())
        lines.append(f"- '{skill.name}': {description}")
    lines.append(
        "Use the 'loadSkill' tool to load the full instructions of a skill when "
        "needed. You can also load additional files referenced by a skill by "
        "passing the optional 'filename' argument."
    )
    return "\n".join(lines)


__all__ = [
    "SKILLS_DIRECTORY",
    "SKILL_DESCRIPTION_MAX_LENGTH",
    "SKILL_FILE_NAME",
    "SKILL_NAME_MAX_LENGTH",
    "Skill",
    "SkillRegistry",
    "build_skills_prompt",
    "compose_skill_document",
    "discover_skills",
    "is_valid_skill_name",
    "normalize_skill_name",
    "parse_frontmatter",
    "read_skill_metadata",
    "split_skill_document",
]
