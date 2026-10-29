"""文件 / 目录工具实现。

每个处理器接收 ``ToolContext`` 和参数字典，返回统一 JSON 字符串。
这里不包含任何 UI 或控制台输出，结果完全通过返回值传递给上层。
"""

from __future__ import annotations

import mimetypes
import os
import shutil
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import Tool, ToolContext
from .helpers import (
    append_text,
    as_bool,
    fail,
    is_protected,
    is_text_file,
    ok,
    on_rm_error,
    read_text,
    resolve_path,
    write_text,
)


def _schema(
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
    }


def _path_property(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


# ---------------------------------------------------------------------------
# 查询 / 只读工具
# ---------------------------------------------------------------------------


def get_current_directory(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    return ok(directory=str(context.base_dir))


def list_directory(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    path = resolve_path(context, arguments.get("directory", "."))
    if not path.exists():
        return fail("目录不存在", directory=str(path))
    if not path.is_dir():
        return fail("目标不是目录", directory=str(path))

    try:
        children = sorted(
            path.iterdir(),
            key=lambda item: (item.is_file(), item.name.lower()),
        )
    except OSError as exc:
        return fail(f"无法读取目录: {exc}", directory=str(path))

    entries = []
    for child in children:
        try:
            info = child.stat()
        except OSError:
            continue

        is_dir = child.is_dir()
        item: dict[str, Any] = {
            "name": child.name,
            "type": "directory" if is_dir else "file",
            "size": None if is_dir else info.st_size,
            "modified": datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }
        if not is_dir:
            mime, _ = mimetypes.guess_type(child.name)
            item["extension"] = child.suffix.lower() or "(无)"
            item["mime_type"] = mime or "未知"
        entries.append(item)

    return ok(directory=str(path), count=len(entries), entries=entries)


def get_file_type(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    target = resolve_path(context, arguments.get("path"))
    if not target.exists():
        return fail("文件或目录不存在", path=str(target))

    if target.is_dir():
        return ok(path=str(target), type="directory", is_text=False)

    mime, encoding = mimetypes.guess_type(target.name)
    try:
        size = target.stat().st_size
    except OSError as exc:
        return fail(f"无法读取文件信息: {exc}", path=str(target))

    return ok(
        path=str(target),
        type="file",
        extension=target.suffix.lower() or "(无)",
        mime_type=mime or "未知",
        mime_encoding=encoding,
        is_text=is_text_file(target),
        size=size,
    )


def read_text_file(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    target = resolve_path(context, arguments.get("path"))
    if not target.exists():
        return fail("文件不存在", path=str(target))
    if not target.is_file():
        return fail("目标不是文件", path=str(target))
    if not is_text_file(target):
        return fail("仅支持读取纯文本文件", path=str(target))

    try:
        text, encoding = read_text(target)
        size = target.stat().st_size
    except (OSError, ValueError) as exc:
        return fail(str(exc), path=str(target))

    limit = context.max_read_chars
    truncated = len(text) > limit
    return ok(
        path=str(target),
        encoding=encoding,
        size=size,
        total_chars=len(text),
        truncated=truncated,
        content=text[:limit],
    )


# ---------------------------------------------------------------------------
# 创建 / 编辑工具
# ---------------------------------------------------------------------------


def create_file(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    directory_path = resolve_path(context, arguments.get("directory"))
    name = str(arguments.get("filename", "")).strip()

    if (
        not name
        or name in {".", ".."}
        or Path(name).name != name
        or "/" in name
        or "\\" in name
    ):
        return fail(
            "filename 只能是文件名，不能包含路径分隔符；"
            "如需放到子目录，请用 directory 参数指定"
        )

    if directory_path.exists() and not directory_path.is_dir():
        return fail("directory 指向的是文件而不是目录", directory=str(directory_path))

    directory_created = not directory_path.exists()
    target = directory_path / name
    target_existed = target.exists()

    if target_existed:
        if target.is_dir():
            return fail("同名目录已存在", path=str(target))
        if not as_bool(arguments.get("overwrite"), default=False):
            return fail("文件已存在，如需覆盖请设置 overwrite=true", path=str(target))

    try:
        directory_path.mkdir(parents=True, exist_ok=True)
        write_text(target, str(arguments.get("content", "")))
        size = target.stat().st_size
    except OSError as exc:
        return fail(f"创建文件失败: {exc}", path=str(target))

    return ok(
        path=str(target),
        size=size,
        directory_created=directory_created,
        overwritten=target_existed,
    )


def edit_text_file(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    target = resolve_path(context, arguments.get("path"))
    if not target.exists():
        return fail("文件不存在", path=str(target))
    if not target.is_file():
        return fail("目标不是文件", path=str(target))
    if not is_text_file(target):
        return fail("仅支持编辑纯文本文件", path=str(target))

    mode = str(arguments.get("mode", "replace")).lower()
    content = str(arguments.get("content", ""))
    old_string = str(arguments.get("old_string", ""))
    new_string = str(arguments.get("new_string", ""))

    try:
        if mode == "overwrite":
            write_text(target, content)
            return ok(path=str(target), mode=mode, size=target.stat().st_size)

        if mode == "append":
            append_text(target, content)
            return ok(path=str(target), mode=mode, size=target.stat().st_size)

        if mode == "replace":
            if not old_string:
                return fail("replace 模式必须提供非空的 old_string")
            text, _ = read_text(target)
            occurrences = text.count(old_string)
            if occurrences == 0:
                return fail("未在文件中找到 old_string", path=str(target))

            if as_bool(arguments.get("replace_all"), default=False):
                new_text = text.replace(old_string, new_string)
                replaced = occurrences
            else:
                new_text = text.replace(old_string, new_string, 1)
                replaced = 1

            write_text(target, new_text)
            return ok(
                path=str(target),
                mode=mode,
                replaced=replaced,
                remaining=occurrences - replaced,
                size=target.stat().st_size,
            )

        return fail("mode 必须是 replace、append 或 overwrite")
    except (OSError, ValueError) as exc:
        return fail(f"编辑文件失败: {exc}", path=str(target))


def create_directory(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    target = resolve_path(context, arguments.get("path"))
    if target.exists():
        if target.is_dir():
            return ok(path=str(target), created=False, message="目录已存在")
        return fail("同名文件已存在，无法创建目录", path=str(target))

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return fail(f"创建目录失败: {exc}", path=str(target))

    return ok(path=str(target), created=True)


# ---------------------------------------------------------------------------
# 删除 / 重命名工具
# ---------------------------------------------------------------------------


def delete_directory(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    target = resolve_path(context, arguments.get("path"))
    if not target.exists():
        return fail("目录不存在", path=str(target))
    if not target.is_dir():
        return fail("目标不是目录，如需删除文件请使用 delete_file", path=str(target))

    reason = is_protected(context, target)
    if reason:
        return fail(reason, path=str(target))

    file_count = 0
    dir_count = 0
    for _, dirs, files in os.walk(target):
        file_count += len(files)
        dir_count += len(dirs)

    try:
        shutil.rmtree(target, onerror=on_rm_error)
    except OSError as exc:
        return fail(f"删除目录失败: {exc}", path=str(target))

    return ok(
        path=str(target),
        deleted=True,
        deleted_files=file_count,
        deleted_subdirectories=dir_count,
    )


def delete_file(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    target = resolve_path(context, arguments.get("path"))
    if not target.exists():
        return fail("文件不存在", path=str(target))
    if target.is_dir():
        return fail("目标不是文件，如需删除目录请使用 delete_directory", path=str(target))

    reason = is_protected(context, target)
    if reason:
        return fail(reason, path=str(target))

    try:
        size = target.stat().st_size
        target.unlink()
    except OSError:
        # Windows 下只读文件需要先去掉只读属性
        try:
            os.chmod(target, 0o700)
            size = target.stat().st_size
            target.unlink()
        except OSError as retry_exc:
            return fail(f"删除文件失败: {retry_exc}", path=str(target))

    return ok(path=str(target), deleted=True, size=size)


def rename_path(context: ToolContext, arguments: Mapping[str, Any]) -> str:
    src = resolve_path(context, arguments.get("source"))
    if not src.exists():
        return fail("源路径不存在", source=str(src))

    reason = is_protected(context, src)
    if reason:
        return fail(reason, source=str(src))

    raw_destination = str(arguments.get("destination", "")).strip().strip('"').strip("'")
    if not raw_destination:
        return fail("destination 不能为空")

    # 只给新名字时，默认在原路径所在目录下重命名
    if not Path(raw_destination).is_absolute() and os.path.dirname(raw_destination) == "":
        dst = (src.parent / raw_destination).resolve()
    else:
        dst = resolve_path(context, raw_destination)

    if src == dst:
        return fail("源路径和目标路径相同")
    if dst in src.parents:
        return fail("不能把目录移动到它自身的子目录中")

    if dst.exists():
        if not as_bool(arguments.get("overwrite"), default=False):
            return fail(
                "目标路径已存在，如需覆盖文件请设置 overwrite=true",
                destination=str(dst),
            )
        if dst.is_dir():
            return fail("目标路径是同名目录，无法覆盖", destination=str(dst))
        reason = is_protected(context, dst)
        if reason:
            return fail(reason, destination=str(dst))
        try:
            dst.unlink()
        except OSError as exc:
            return fail(f"覆盖目标文件失败: {exc}", destination=str(dst))

    try:
        shutil.move(str(src), str(dst))
    except (OSError, shutil.Error) as exc:
        return fail("重命名失败: " + str(exc), source=str(src), destination=str(dst))

    return ok(
        source=str(src),
        destination=str(dst),
        type="directory" if dst.is_dir() else "file",
    )


def build_filesystem_tools() -> list[Tool]:
    """构造全部文件 / 目录工具。"""

    return [
        Tool(
            name="get_current_directory",
            description="获取当前工作目录的绝对路径",
            parameters=_schema({}),
            handler=get_current_directory,
        ),
        Tool(
            name="list_directory",
            description="列出指定目录下的所有文件和子目录，包含名称、类型、大小和修改时间",
            parameters=_schema(
                {
                    "directory": _path_property(
                        "目录路径，绝对路径或以当前工作目录为基准的相对路径，默认为当前目录"
                    )
                }
            ),
            handler=list_directory,
        ),
        Tool(
            name="get_file_type",
            description="获取指定文件或目录的类型信息，包括扩展名、MIME 类型以及是否为纯文本文件",
            parameters=_schema(
                {"path": _path_property("文件或目录的路径")},
                ["path"],
            ),
            handler=get_file_type,
        ),
        Tool(
            name="read_text_file",
            description=(
                "读取指定纯文本文件的内容，仅支持文本格式"
                "（如 .txt、.md、.py、.json、.csv 等），拒绝二进制文件"
            ),
            parameters=_schema(
                {"path": _path_property("要读取的纯文本文件路径")},
                ["path"],
            ),
            handler=read_text_file,
        ),
        Tool(
            name="create_file",
            description=(
                "在指定目录下创建新文件，如果目录不存在会自动逐级创建；"
                "默认不覆盖已存在的文件"
            ),
            parameters=_schema(
                {
                    "directory": _path_property("目标目录路径，不存在时会自动创建"),
                    "filename": {
                        "type": "string",
                        "description": "文件名，只能包含文件名本身，不能带路径分隔符",
                    },
                    "content": {
                        "type": "string",
                        "description": "文件初始内容，默认为空字符串",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "文件已存在时是否覆盖，默认 false",
                    },
                },
                ["directory", "filename"],
            ),
            handler=create_file,
        ),
        Tool(
            name="edit_text_file",
            description=(
                "编辑指定纯文本文件的内容。mode=overwrite 用 content 覆盖整个文件；"
                "mode=append 把 content 追加到文件末尾；"
                "mode=replace 把 old_string 替换为 new_string"
                "（默认只替换第一处，replace_all=true 替换全部）"
            ),
            parameters=_schema(
                {
                    "path": _path_property("要编辑的纯文本文件路径"),
                    "mode": {
                        "type": "string",
                        "enum": ["replace", "append", "overwrite"],
                        "description": "编辑模式，默认 replace",
                    },
                    "content": {
                        "type": "string",
                        "description": "overwrite / append 模式下要写入的内容",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "replace 模式下要被替换的原文本，必须非空",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "replace 模式下替换后的新文本，默认空字符串表示删除原文本",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "replace 模式下是否替换所有匹配项，默认 false",
                    },
                },
                ["path"],
            ),
            handler=edit_text_file,
        ),
        Tool(
            name="create_directory",
            description="创建一个新目录，父目录不存在时会逐级自动创建",
            parameters=_schema(
                {"path": _path_property("要创建的目录路径")},
                ["path"],
            ),
            handler=create_directory,
        ),
        Tool(
            name="delete_directory",
            description=(
                "删除指定目录，支持删除非空目录（包含其中的所有文件和子目录），"
                "操作不可恢复"
            ),
            parameters=_schema(
                {"path": _path_property("要删除的目录路径")},
                ["path"],
            ),
            handler=delete_directory,
        ),
        Tool(
            name="delete_file",
            description="删除指定文件，操作不可恢复；不能用于删除目录",
            parameters=_schema(
                {"path": _path_property("要删除的文件路径")},
                ["path"],
            ),
            handler=delete_file,
        ),
        Tool(
            name="rename_path",
            description=(
                "重命名文件或目录，也可以把文件/目录移动到新位置；"
                "只给新名字时默认在原目录下重命名"
            ),
            parameters=_schema(
                {
                    "source": _path_property("原文件或目录的路径"),
                    "destination": {
                        "type": "string",
                        "description": "新的路径或新名字；只写名字时表示在原目录下重命名",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "目标文件已存在时是否覆盖，默认 false",
                    },
                },
                ["source", "destination"],
            ),
            handler=rename_path,
        ),
    ]
