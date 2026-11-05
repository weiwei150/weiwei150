"""Load skill instructions and attachments on demand."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..skills import Skill
from .base import Tool, ToolContext
from .helpers import fail, is_text_file, ok, read_text


def _relative_to(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _is_inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for item in paths:
        try:
            key = os.path.normcase(str(item.resolve()))
        except (OSError, ValueError):
            key = os.path.normcase(str(item))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _normalize_filename(raw: object) -> str:
    return str(raw if raw is not None else "").strip().strip('"').strip("'")


def _read_skill_instructions(context: ToolContext, skill: Skill) -> str:
    path = skill.skill_file
    if not path.is_file() or not _is_inside(path, skill.directory):
        return fail(
            f"skill 的 SKILL.md 不存在或不在 skill 目录内: {path}",
            skill=skill.name,
            path=str(path),
        )
    if not is_text_file(path):
        return fail("SKILL.md 不是纯文本文件", skill=skill.name, path=str(path))

    try:
        content, encoding = read_text(path)
        size = path.stat().st_size
    except (OSError, ValueError) as exc:
        return fail(f"读取 SKILL.md 失败: {exc}", skill=skill.name, path=str(path))

    return ok(
        skill=skill.name,
        path=str(path),
        encoding=encoding,
        size=size,
        total_chars=len(content),
        content=content,
    )


def _read_attachment(context: ToolContext, skill: Skill, path: Path) -> str:
    if not path.is_file():
        return fail("目标不是文件", skill=skill.name, path=str(path))
    if not is_text_file(path):
        return fail("仅支持读取纯文本附件", skill=skill.name, path=str(path))

    try:
        content, encoding = read_text(path)
        size = path.stat().st_size
    except (OSError, ValueError) as exc:
        return fail(f"读取附件失败: {exc}", skill=skill.name, path=str(path))

    return ok(
        skill=skill.name,
        path=str(path),
        relative_path=_relative_to(path, skill.directory),
        encoding=encoding,
        size=size,
        total_chars=len(content),
        content=content,
    )


def _exact_candidates(context: ToolContext, skill: Skill, filename: str) -> list[Path]:
    expanded = Path(os.path.expandvars(os.path.expanduser(filename)))
    candidates: list[Path] = []
    if expanded.is_absolute():
        candidates.append(expanded)
    else:
        candidates.append(skill.directory / expanded)
        candidates.append(context.base_dir / expanded)
    return _dedupe_paths(candidates)


def _search_by_filename(skill: Skill, filename: str) -> list[Path]:
    """Find all matching filenames recursively within a skill directory."""

    target = filename.casefold()
    try:
        matches = [
            item
            for item in skill.directory.rglob("*")
            if item.is_file()
            and item.name.casefold() == target
            and _is_inside(item, skill.directory)
        ]
    except OSError:
        return []

    unique = _dedupe_paths(matches)
    return sorted(
        unique,
        key=lambda item: _relative_to(item, skill.directory).casefold(),
    )


def _load_attachment(context: ToolContext, skill: Skill, filename: str) -> str:
    exact = _exact_candidates(context, skill, filename)
    outside: list[Path] = []
    directories: list[Path] = []

    for candidate in exact:
        if not _is_inside(candidate, skill.directory):
            if candidate.exists():
                outside.append(candidate)
            continue
        if candidate.is_file():
            return _read_attachment(context, skill, candidate)
        if candidate.exists() and candidate.is_dir():
            directories.append(candidate)

    is_bare_filename = not any(separator in filename for separator in ("/", "\\"))
    if is_bare_filename:
        matches = _search_by_filename(skill, filename)
        if len(matches) == 1:
            return _read_attachment(context, skill, matches[0])
        if len(matches) > 1:
            return fail(
                "在 skill 目录中找到多个同名文件，请指定完整路径后重试",
                skill=skill.name,
                filename=filename,
                candidates=[str(item) for item in matches],
                reason="multiple_matches",
            )

    if outside:
        return fail(
            "文件路径超出指定 skill 的目录范围",
            skill=skill.name,
            filename=filename,
            path=str(outside[0]),
            reason="outside_skill_directory",
        )
    if directories:
        return fail(
            "filename 指向的是目录而不是文件",
            skill=skill.name,
            filename=filename,
            path=str(directories[0]),
        )

    return fail(
        "在 skill 目录中未找到指定附件",
        skill=skill.name,
        filename=filename,
        tried=[str(item) for item in exact],
        reason="file_not_found",
    )


def load_skill(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    """Load a skill's instructions or one attachment."""

    name = _normalize_filename(arguments.get("name"))
    if not name:
        return fail("name 不能为空", reason="missing_name")

    registry = context.skills
    if registry is None or not len(registry):
        return fail(
            "当前没有可用的 skill，未在项目根目录的 .agents/skills 中发现任何 skill",
            reason="no_skills",
        )

    skill = registry.get(name)
    if skill is None:
        return fail(
            f"未找到 skill: {name}",
            name=name,
            available=list(registry.names),
            reason="skill_not_found",
        )

    filename = _normalize_filename(arguments.get("filename"))
    if not filename:
        return _read_skill_instructions(context, skill)
    return _load_attachment(context, skill, filename)


def build_skill_tools() -> list[Tool]:
    """Build the skill-loading tool."""

    return [
        Tool(
            name="loadSkill",
            description=(
                "加载一个已注册 skill 的完整指令，或读取该 skill 目录中的附件文件。"
                "只提供 name 时读取 SKILL.md 全文；同时提供 filename 时读取对应附件，"
                "不会重复加载 SKILL.md。filename 支持相对于 skill 目录、相对于项目"
                "工作目录以及绝对路径；只写文件名时会在该 skill 目录内递归查找，"
                "匹配到多个同名文件时返回候选路径。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "skill 的名称，即 system prompt 中列出的名称",
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "可选。需要加载的 skill 附件文件路径或文件名；"
                            "省略时加载该 skill 的 SKILL.md"
                        ),
                    },
                },
                "required": ["name"],
            },
            handler=load_skill,
        )
    ]


__all__ = ["build_skill_tools", "load_skill"]