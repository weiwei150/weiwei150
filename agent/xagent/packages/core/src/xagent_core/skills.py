"""Agent Skills discovery and registry.

Each directory under ``.agents/skills/`` is a skill and must contain a
``SKILL.md`` file with ``name`` and ``description`` frontmatter fields.
Only metadata is loaded at startup; the body is loaded on demand by the
``loadSkill`` tool.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIRECTORY = Path(".agents") / "skills"
SKILL_FILE_NAME = "skill.md"

_FRONTMATTER_DELIMITERS = {"---", "..."}
_KEY_RE = re.compile(r"^([^:#][^:]*?):(?:[ \t]+(.*))?$")


@dataclass(frozen=True)
class Skill:
    """Metadata for a discovered skill."""

    name: str
    description: str
    directory: Path
    skill_file: Path


class SkillRegistry:
    """Discovered skills with lookup by name."""

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
        """The scanned skills directory, or its expected path if absent."""

        return self._root

    @property
    def warnings(self) -> tuple[str, ...]:
        """Invalid skill directories skipped during discovery."""

        return self._warnings

    def get(self, name: str) -> Skill | None:
        """Match exactly, then allow a unique case-insensitive match."""

        skill = self._by_name.get(name)
        if skill is not None:
            return skill
        matches = [
            item for item in self._skills if item.name.casefold() == name.casefold()
        ]
        return matches[0] if len(matches) == 1 else None

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

    value = re.split(r"[ \t]+#", value, maxsplit=1)[0].rstrip()
    if value in {"~", "null", "Null", "NULL"}:
        return ""
    return value


def _parse_yaml_subset(lines: list[str]) -> dict[str, str]:
    """Parse the small YAML subset needed by skill frontmatter."""

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
    """Extract frontmatter fields, returning an empty mapping when absent."""

    lines = text.splitlines()
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return {}

    for end in range(1, len(lines)):
        if lines[end].strip() in _FRONTMATTER_DELIMITERS:
            return _parse_yaml_subset(lines[1:end])
    return {}


def _read_frontmatter_text(path: Path) -> str | None:
    """Read only through the frontmatter closing delimiter."""

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
    """Read frontmatter without retaining the skill body."""

    frontmatter = _read_frontmatter_text(path)
    if frontmatter is None:
        return {}
    return parse_frontmatter(frontmatter)


def _find_skill_file(directory: Path) -> Path | None:
    """Find a direct-child SKILL.md, case-insensitively."""

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
    """Discover valid skills beneath ``<project_root>/.agents/skills``."""

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
    """Build the system-prompt skill list, or an empty string when unavailable."""

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
    "SKILL_FILE_NAME",
    "Skill",
    "SkillRegistry",
    "build_skills_prompt",
    "discover_skills",
    "parse_frontmatter",
    "read_skill_metadata",
]