"""``loadSkill`` 工具：按需加载 skill 指令和附件。

skill 正文只在模型主动调用本工具时进入对话上下文。所有附件读取都被限制在
对应 skill 目录内部，避免 ``..``、绝对路径或符号链接把读取范围带到目录之外。
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..skills import (
    SKILLS_DIRECTORY,
    Skill,
    compose_skill_document,
    is_valid_skill_name,
    normalize_skill_name,
)
from .base import Tool, ToolContext
from .helpers import fail, is_text_file, ok, read_text, write_text


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
    return (
        str(raw if raw is not None else "")
        .strip()
        .strip('"')
        .strip("'")
    )


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
        # 优先解释为相对 skill 目录的路径，其次才是项目工作目录相对路径
        candidates.append(skill.directory / expanded)
        candidates.append(context.base_dir / expanded)
    return _dedupe_paths(candidates)


def _search_by_filename(skill: Skill, filename: str) -> list[Path]:
    """在 skill 目录中递归查找同名文件，返回全部候选。"""

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
        # 明确拒绝目录外路径，即使目标存在也不读取
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
    """加载 skill 的完整 SKILL.md，或该 skill 目录内的附件。"""

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


def _find_existing_skill_directory(skills_root: Path, name: str) -> Path | None:
    target = skills_root / name
    if target.exists():
        return target
    try:
        for child in skills_root.iterdir():
            if child.is_dir() and child.name.casefold() == name.casefold():
                return child
    except OSError:
        pass
    return None


def create_skill(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    """在当前项目的 ``.agents/skills`` 下创建新 skill 的 SKILL.md。"""

    raw_name = _normalize_filename(arguments.get("name"))
    if not raw_name:
        return fail("name 不能为空", reason="missing_name")

    name = normalize_skill_name(raw_name)
    if not is_valid_skill_name(name):
        if len(name) > 64:
            message = "Skill 名称过长，规范化后不能超过 64 个字符"
        else:
            message = (
                "Skill 名称无效：请使用小写字母、数字和连字符，"
                "例如 'pdf-tools'"
            )
        return fail(
            message,
            name=name,
            requested_name=raw_name,
            reason="invalid_name",
        )

    raw_context = arguments.get("skillContext")
    if raw_context is None:
        raw_context = ""
    if not isinstance(raw_context, str):
        raw_context = str(raw_context)
    if not raw_context.strip():
        return fail(
            "skillContext 不能为空，必须提供 SKILL.md 的正文内容",
            name=name,
            reason="missing_context",
        )

    registry = context.skills
    existing = registry.get(name) if registry is not None else None
    if existing is not None:
        return fail(
            f"Skill 已存在，未覆盖原有内容: {name}",
            name=name,
            path=str(existing.skill_file),
            reason="skill_exists",
        )

    skills_root = context.base_dir / SKILLS_DIRECTORY
    existing_directory = _find_existing_skill_directory(skills_root, name)
    if existing_directory is not None:
        return fail(
            f"Skill 目录已存在，未覆盖原有内容: {name}",
            name=name,
            path=str(existing_directory),
            reason="skill_exists",
        )

    try:
        document, description = compose_skill_document(name, raw_context)
    except (TypeError, ValueError) as exc:
        return fail(str(exc), name=name, reason="invalid_context")

    skill_directory = skills_root / name
    skill_file = skill_directory / "SKILL.md"
    created = False
    try:
        skills_root.mkdir(parents=True, exist_ok=True)
        skill_directory.mkdir()
        created = True
        write_text(skill_file, document)
        size = skill_file.stat().st_size
    except FileExistsError:
        return fail(
            f"Skill 目录已存在，未覆盖原有内容: {name}",
            name=name,
            path=str(skill_directory),
            reason="skill_exists",
        )
    except OSError as exc:
        if created:
            shutil.rmtree(skill_directory, ignore_errors=True)
        return fail(
            f"创建 Skill 失败: {exc}",
            name=name,
            path=str(skill_directory),
            reason="write_failed",
        )

    skill = Skill(
        name=name,
        description=description,
        directory=skill_directory.resolve(),
        skill_file=skill_file.resolve(),
    )
    if registry is not None:
        try:
            registry.register(skill)
        except ValueError:
            # 目录与文件已经成功创建；注册冲突通常来自并发写入，不应回滚文件
            pass

    return ok(
        skill=name,
        path=str(skill_file),
        directory=str(skill_directory),
        description=description,
        size=size,
        created=True,
        message=(
            "Skill 已创建。如需补充 references/、scripts/ 等目录或辅助文件，"
            "请继续使用 create_directory、create_file 等文件工具。"
        ),
    )


def build_skill_tools() -> list[Tool]:
    """构造 skill 创建与加载工具。"""

    return [
        Tool(
            name="createSkill",
            description=(
                "当用户要求创建新的 Agent Skill 时调用。工具会在当前项目根目录的 "
                ".agents/skills/ 下创建与 name 对应的英文子目录并生成 SKILL.md，"
                "自动确保文件包含合法的 YAML frontmatter、name、description 和正文。"
                "Skill 名称会规范化为小写字母、数字和连字符；如果同名 Skill 已存在"
                "则返回错误且不覆盖。本工具只创建 SKILL.md，不会创建 references/、"
                "scripts/ 等目录或其他辅助文件；如需这些内容，请继续调用现有的"
                "文件系统工具。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Skill 名称，会规范化为小写字母、数字和连字符，"
                            "例如 'pdf-tools'"
                        ),
                    },
                    "skillContext": {
                        "type": "string",
                        "description": (
                            "写入 SKILL.md 的完整内容。可以包含 YAML frontmatter"
                            "（其中 description 会被复用），也可以只提供正文；"
                            "缺少 description 时会从正文首段自动推导。"
                        ),
                    },
                },
                "required": ["name", "skillContext"],
            },
            handler=create_skill,
        ),
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
        ),
    ]


__all__ = ["build_skill_tools", "create_skill", "load_skill"]
