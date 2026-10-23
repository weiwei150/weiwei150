"""
基于 chat.py 扩展的本地文件操作 Agent。

在原 getDate 工具的基础上，新增 10 个文件/目录操作工具：
  1. get_current_directory  获取当前工作目录
  2. list_directory         列出指定目录下的文件和子目录
  3. get_file_type          获取文件类型（扩展名 / MIME / 是否为纯文本）
  4. read_text_file         读取纯文本文件内容
  5. create_file            在指定目录下创建文件（自动创建缺失的目录）
  6. edit_text_file         编辑纯文本文件（覆盖 / 追加 / 替换）
  7. create_directory       创建目录
  8. delete_directory       删除目录（支持非空目录）
  9. delete_file            删除文件
 10. rename_path            重命名文件或目录

运行方式：
    python file_agent.py

说明：
  - 相对路径以启动脚本时的工作目录为基准；
  - 所有工具统一返回 JSON 字符串，便于模型判断 success / error；
  - 删除、覆盖等破坏性操作带有基础的安全保护（拒绝磁盘根目录、当前工作目录、用户主目录）。
"""

import configparser
import json
import mimetypes
import os
import shutil
import stat
import subprocess
from datetime import datetime
from pathlib import Path

from openai import OpenAI

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

BASE_DIR = Path.cwd().resolve()  # 相对路径的基准目录
MAX_READ_CHARS = 20000  # 单次读取返回给模型的最大字符数

# 明确按纯文本处理的后缀
TEXT_EXTENSIONS = {
    ".txt", ".text", ".log", ".md", ".markdown", ".rst", ".tex",
    ".py", ".pyw", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".vue",
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".properties", ".env", ".csv", ".tsv", ".xml", ".html", ".htm", ".css",
    ".scss", ".less", ".sass", ".sql", ".sh", ".bash", ".zsh", ".bat",
    ".cmd", ".ps1", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".java",
    ".kt", ".go", ".rs", ".rb", ".php", ".pl", ".lua", ".r", ".swift",
    ".gradle", ".dockerfile", ".gitignore", ".gitattributes", ".editorconfig",
}

TEXT_MIME_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/javascript",
    "application/x-javascript",
    "application/x-yaml",
    "application/yaml",
    "application/x-sh",
    "application/sql",
}

config = configparser.ConfigParser()
config.read(Path(__file__).with_name("config.ini"), encoding="utf-8")

base_url = config["llm"]["base_url"]
model_name = config["llm"]["model_name"]
api_key = config["llm"]["api_key"]

client = OpenAI(base_url=base_url, api_key=api_key)

SYSTEM_PROMPT = (
    "你是一个可以操作本地计算机的助手，可以查询当前时间，也可以读写本地文件和目录。"
    "调用工具时请使用明确、完整的路径；相对路径以程序启动时的工作目录为基准。"
    "执行删除、重命名、覆盖等破坏性操作前，先确认目标路径存在，"
    "并且避免操作系统目录、用户主目录或当前工作目录本身。"
    "所有工具都会返回 JSON 结果，请根据 success 和 error 字段判断是否成功，"
    "失败时向用户说明原因，不要假装成功。"
)


# ---------------------------------------------------------------------------
# 通用工具函数
# ---------------------------------------------------------------------------

def _ok(**data) -> str:
    return json.dumps({"success": True, **data}, ensure_ascii=False, indent=2)


def _fail(message: str, **data) -> str:
    return json.dumps({"success": False, "error": message, **data}, ensure_ascii=False, indent=2)


def _resolve(path: str) -> Path:
    """把用户/模型传入的路径解析为绝对路径（相对路径基于 BASE_DIR）。"""
    text = str(path if path is not None else "").strip().strip('"').strip("'")
    if not text:
        raise ValueError("路径不能为空")
    p = Path(os.path.expandvars(os.path.expanduser(text)))
    if not p.is_absolute():
        p = BASE_DIR / p
    return p.resolve()


def _is_protected(path: Path) -> str | None:
    """判断路径是否属于禁止删除/覆盖的高危目录，返回拒绝原因或 None。"""
    if path == path.parent:
        return "拒绝操作磁盘根目录"
    if path == BASE_DIR:
        return "拒绝操作当前工作目录本身"
    if path == Path.home().resolve():
        return "拒绝操作用户主目录"
    if path in BASE_DIR.parents:
        return "拒绝操作当前工作目录的上级目录"
    return None


def _decode_text(raw: bytes):
    """尝试把字节解码为文本，返回 (文本, 编码) 或 (None, None)。"""
    for cut in range(4):
        if cut and len(raw) <= cut:
            break
        chunk = raw[: len(raw) - cut] if cut else raw
        if b"\x00" in chunk:
            return None, None
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return chunk.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
    return None, None


def _is_text_file(path: Path) -> bool:
    """根据扩展名、MIME 类型和内容判断是否为纯文本文件。"""
    extension = path.suffix.lower()
    mime, _ = mimetypes.guess_type(path.name)

    if extension in TEXT_EXTENSIONS:
        return True
    if mime and (mime.startswith("text/") or mime in TEXT_MIME_TYPES):
        return True
    if mime is not None:  # 已知的二进制类型（图片、压缩包、可执行文件等）
        return False

    # 类型未知时尝试按文本解码
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
    except OSError:
        return False
    text, _ = _decode_text(head)
    return text is not None


def _read_text_file(path: Path):
    """读取纯文本文件，返回 (文本, 编码)。"""
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("该文件包含二进制内容，不是纯文本文件")
    text, encoding = _decode_text(raw)
    if text is None:
        raise ValueError("无法按 UTF-8 / GB18030 解码该文件，可能不是纯文本文件")
    return text, encoding


def _write_text_file(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _on_rm_error(func, path, exc_info):
    """删除只读文件时先去掉只读属性再重试。"""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 原有的工具
# ---------------------------------------------------------------------------

def get_date() -> str:
    result = subprocess.run(
        "date /t & time /t",
        shell=True,
        capture_output=True,
        text=True,
    )
    output = result.stdout.strip()
    return output


# ---------------------------------------------------------------------------
# 新增工具 1：获取当前目录
# ---------------------------------------------------------------------------

def get_current_directory() -> str:
    return _ok(directory=os.getcwd())


# ---------------------------------------------------------------------------
# 新增工具 2：列出目录内容
# ---------------------------------------------------------------------------

def list_directory(directory: str = ".") -> str:
    path = _resolve(directory)
    if not path.exists():
        return _fail("目录不存在", directory=str(path))
    if not path.is_dir():
        return _fail("目标不是目录", directory=str(path))

    try:
        children = sorted(
            path.iterdir(),
            key=lambda item: (item.is_file(), item.name.lower()),
        )
    except OSError as exc:
        return _fail(f"无法读取目录: {exc}", directory=str(path))

    entries = []
    for child in children:
        try:
            info = child.stat()
        except OSError:
            continue

        is_dir = child.is_dir()
        item = {
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

    return _ok(
        directory=str(path),
        count=len(entries),
        entries=entries,
    )


# ---------------------------------------------------------------------------
# 新增工具 3：获取文件类型
# ---------------------------------------------------------------------------

def get_file_type(path: str) -> str:
    target = _resolve(path)
    if not target.exists():
        return _fail("文件或目录不存在", path=str(target))

    if target.is_dir():
        return _ok(path=str(target), type="directory", is_text=False)

    mime, encoding = mimetypes.guess_type(target.name)
    return _ok(
        path=str(target),
        type="file",
        extension=target.suffix.lower() or "(无)",
        mime_type=mime or "未知",
        mime_encoding=encoding,
        is_text=_is_text_file(target),
        size=target.stat().st_size,
    )


# ---------------------------------------------------------------------------
# 新增工具 4：读取纯文本文件
# ---------------------------------------------------------------------------

def read_text_file(path: str) -> str:
    target = _resolve(path)
    if not target.exists():
        return _fail("文件不存在", path=str(target))
    if not target.is_file():
        return _fail("目标不是文件", path=str(target))
    if not _is_text_file(target):
        return _fail("仅支持读取纯文本文件", path=str(target))

    try:
        text, encoding = _read_text_file(target)
    except (OSError, ValueError) as exc:
        return _fail(str(exc), path=str(target))

    truncated = len(text) > MAX_READ_CHARS
    return _ok(
        path=str(target),
        encoding=encoding,
        size=target.stat().st_size,
        total_chars=len(text),
        truncated=truncated,
        content=text[:MAX_READ_CHARS],
    )


# ---------------------------------------------------------------------------
# 新增工具 5：创建文件（自动创建缺失的目录）
# ---------------------------------------------------------------------------

def create_file(directory: str, filename: str, content: str = "", overwrite: bool = False) -> str:
    directory_path = _resolve(directory)
    name = str(filename).strip()

    if not name or name in (".", "..") or Path(name).name != name:
        return _fail("filename 只能是文件名，不能包含路径分隔符；如需放到子目录，请用 directory 参数指定")

    if directory_path.exists() and not directory_path.is_dir():
        return _fail("directory 指向的是文件而不是目录", directory=str(directory_path))

    directory_created = not directory_path.exists()
    target = directory_path / name
    target_existed = target.exists()

    if target_existed:
        if target.is_dir():
            return _fail("同名目录已存在", path=str(target))
        if not overwrite:
            return _fail("文件已存在，如需覆盖请设置 overwrite=true", path=str(target))

    try:
        directory_path.mkdir(parents=True, exist_ok=True)
        _write_text_file(target, str(content))
    except OSError as exc:
        return _fail(f"创建文件失败: {exc}", path=str(target))

    return _ok(
        path=str(target),
        size=target.stat().st_size,
        directory_created=directory_created,
        overwritten=target_existed,
    )


# ---------------------------------------------------------------------------
# 新增工具 6：编辑纯文本文件
# ---------------------------------------------------------------------------

def edit_text_file(
    path: str,
    mode: str = "replace",
    content: str = "",
    old_string: str = "",
    new_string: str = "",
    replace_all: bool = False,
) -> str:
    target = _resolve(path)
    if not target.exists():
        return _fail("文件不存在", path=str(target))
    if not target.is_file():
        return _fail("目标不是文件", path=str(target))
    if not _is_text_file(target):
        return _fail("仅支持编辑纯文本文件", path=str(target))

    mode = str(mode).lower()

    try:
        if mode == "overwrite":
            _write_text_file(target, str(content))
            return _ok(path=str(target), mode=mode, size=target.stat().st_size)

        if mode == "append":
            with open(target, "a", encoding="utf-8", newline="\n") as f:
                f.write(str(content))
            return _ok(path=str(target), mode=mode, size=target.stat().st_size)

        if mode == "replace":
            if not old_string:
                return _fail("replace 模式必须提供非空的 old_string")
            text, _ = _read_text_file(target)
            occurrences = text.count(old_string)
            if occurrences == 0:
                return _fail("未在文件中找到 old_string", path=str(target))
            if replace_all:
                new_text = text.replace(old_string, new_string)
                replaced = occurrences
            else:
                new_text = text.replace(old_string, new_string, 1)
                replaced = 1
            _write_text_file(target, new_text)
            return _ok(
                path=str(target),
                mode=mode,
                replaced=replaced,
                remaining=occurrences - replaced,
                size=target.stat().st_size,
            )

        return _fail("mode 必须是 replace、append 或 overwrite")
    except (OSError, ValueError) as exc:
        return _fail(f"编辑文件失败: {exc}", path=str(target))


# ---------------------------------------------------------------------------
# 新增工具 7：创建目录
# ---------------------------------------------------------------------------

def create_directory(path: str) -> str:
    target = _resolve(path)
    if target.exists():
        if target.is_dir():
            return _ok(path=str(target), created=False, message="目录已存在")
        return _fail("同名文件已存在，无法创建目录", path=str(target))

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _fail(f"创建目录失败: {exc}", path=str(target))

    return _ok(path=str(target), created=True)


# ---------------------------------------------------------------------------
# 新增工具 8：删除目录（支持非空）
# ---------------------------------------------------------------------------

def delete_directory(path: str) -> str:
    target = _resolve(path)
    if not target.exists():
        return _fail("目录不存在", path=str(target))
    if not target.is_dir():
        return _fail("目标不是目录，如需删除文件请使用 delete_file", path=str(target))

    reason = _is_protected(target)
    if reason:
        return _fail(reason, path=str(target))

    file_count = 0
    dir_count = 0
    for _, dirs, files in os.walk(target):
        file_count += len(files)
        dir_count += len(dirs)

    try:
        shutil.rmtree(target, onerror=_on_rm_error)
    except OSError as exc:
        return _fail(f"删除目录失败: {exc}", path=str(target))

    return _ok(
        path=str(target),
        deleted=True,
        deleted_files=file_count,
        deleted_subdirectories=dir_count,
    )


# ---------------------------------------------------------------------------
# 新增工具 9：删除文件
# ---------------------------------------------------------------------------

def delete_file(path: str) -> str:
    target = _resolve(path)
    if not target.exists():
        return _fail("文件不存在", path=str(target))
    if target.is_dir():
        return _fail("目标不是文件，如需删除目录请使用 delete_directory", path=str(target))

    reason = _is_protected(target)
    if reason:
        return _fail(reason, path=str(target))

    try:
        size = target.stat().st_size
        target.unlink()
    except OSError as exc:
        # Windows 下只读文件需要先去掉只读属性
        try:
            os.chmod(target, stat.S_IWRITE)
            target.unlink()
        except OSError:
            return _fail(f"删除文件失败: {exc}", path=str(target))

    return _ok(path=str(target), deleted=True, size=size)


# ---------------------------------------------------------------------------
# 新增工具 10：重命名文件或目录
# ---------------------------------------------------------------------------

def rename_path(source: str, destination: str, overwrite: bool = False) -> str:
    src = _resolve(source)
    if not src.exists():
        return _fail("源路径不存在", source=str(src))

    reason = _is_protected(src)
    if reason:
        return _fail(reason, source=str(src))

    raw_destination = str(destination if destination is not None else "").strip().strip('"').strip("'")
    if not raw_destination:
        return _fail("destination 不能为空")

    # 只给新名字时，默认在原路径所在目录下重命名
    if not Path(raw_destination).is_absolute() and os.path.dirname(raw_destination) == "":
        dst = (src.parent / raw_destination).resolve()
    else:
        dst = _resolve(raw_destination)

    if src == dst:
        return _fail("源路径和目标路径相同")
    if dst in src.parents:
        return _fail("不能把目录移动到它自身的子目录中")

    if dst.exists():
        if not overwrite:
            return _fail("目标路径已存在，如需覆盖文件请设置 overwrite=true", destination=str(dst))
        if dst.is_dir():
            return _fail("目标路径是同名目录，无法覆盖", destination=str(dst))
        reason = _is_protected(dst)
        if reason:
            return _fail(reason, destination=str(dst))
        try:
            dst.unlink()
        except OSError as exc:
            return _fail(f"覆盖目标文件失败: {exc}", destination=str(dst))

    try:
        shutil.move(str(src), str(dst))
    except (OSError, shutil.Error) as exc:
        return _fail(f"重命名失败: {exc}", source=str(src), destination=str(dst))

    return _ok(
        source=str(src),
        destination=str(dst),
        type="directory" if dst.is_dir() else "file",
    )


# ---------------------------------------------------------------------------
# 工具定义（给模型看的 schema）
# ---------------------------------------------------------------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间，通过调用本地 date/time 命令实现",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_directory",
            "description": "获取当前工作目录的绝对路径",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "列出指定目录下的所有文件和子目录，包含名称、类型、大小和修改时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "目录路径，绝对路径或以当前工作目录为基准的相对路径，默认为当前目录",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_type",
            "description": "获取指定文件或目录的类型信息，包括扩展名、MIME 类型以及是否为纯文本文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件或目录的路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_text_file",
            "description": "读取指定纯文本文件的内容，仅支持文本格式（如 .txt、.md、.py、.json、.csv 等），拒绝二进制文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要读取的纯文本文件路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "在指定目录下创建新文件，如果目录不存在会自动逐级创建；默认不覆盖已存在的文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "目标目录路径，不存在时会自动创建",
                    },
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
                "required": ["directory", "filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_text_file",
            "description": (
                "编辑指定纯文本文件的内容。mode=overwrite 用 content 覆盖整个文件；"
                "mode=append 把 content 追加到文件末尾；"
                "mode=replace 把 old_string 替换为 new_string（默认只替换第一处，replace_all=true 替换全部）"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要编辑的纯文本文件路径",
                    },
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
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "创建一个新目录，父目录不存在时会逐级自动创建",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要创建的目录路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_directory",
            "description": "删除指定目录，支持删除非空目录（包含其中的所有文件和子目录），操作不可恢复",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的目录路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "删除指定文件，操作不可恢复；不能用于删除目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的文件路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_path",
            "description": "重命名文件或目录，也可以把文件/目录移动到新位置；只给新名字时默认在原目录下重命名",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "原文件或目录的路径",
                    },
                    "destination": {
                        "type": "string",
                        "description": "新的路径或新名字；只写名字时表示在原目录下重命名",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "目标文件已存在时是否覆盖，默认 false",
                    },
                },
                "required": ["source", "destination"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# 工具分发
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "getDate": lambda args: get_date(),
    "get_current_directory": lambda args: get_current_directory(),
    "list_directory": lambda args: list_directory(args.get("directory", ".")),
    "get_file_type": lambda args: get_file_type(args["path"]),
    "read_text_file": lambda args: read_text_file(args["path"]),
    "create_file": lambda args: create_file(
        args["directory"],
        args["filename"],
        args.get("content", ""),
        bool(args.get("overwrite", False)),
    ),
    "edit_text_file": lambda args: edit_text_file(
        args["path"],
        args.get("mode", "replace"),
        args.get("content", ""),
        args.get("old_string", ""),
        args.get("new_string", ""),
        bool(args.get("replace_all", False)),
    ),
    "create_directory": lambda args: create_directory(args["path"]),
    "delete_directory": lambda args: delete_directory(args["path"]),
    "delete_file": lambda args: delete_file(args["path"]),
    "rename_path": lambda args: rename_path(
        args["source"],
        args["destination"],
        bool(args.get("overwrite", False)),
    ),
}


def handle_tool_calls(tool_calls) -> list:
    messages = []
    for tool_call in tool_calls:
        function = tool_call["function"]
        name = function["name"]
        raw_arguments = function.get("arguments") or "{}"
        print(f"[工具调用] {name}({raw_arguments})")

        try:
            arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
            if not isinstance(arguments, dict):
                raise ValueError("参数必须是 JSON 对象")
        except (json.JSONDecodeError, ValueError) as exc:
            content = _fail(f"工具参数不是合法的 JSON: {exc}")
        else:
            handler = TOOL_HANDLERS.get(name)
            if handler is None:
                content = _fail(f"未知工具: {name}")
            else:
                try:
                    content = handler(arguments)
                except KeyError as exc:
                    content = _fail(f"缺少必需参数: {exc}")
                except Exception as exc:  # 保证单个工具异常不会中断对话
                    content = _fail(f"{type(exc).__name__}: {exc}")

        preview = content if len(content) <= 1000 else content[:1000] + "\n...（内容已截断）"
        print(f"[工具结果] {preview}")
        print("---")

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": content,
            }
        )
    return messages


# ---------------------------------------------------------------------------
# 主循环（沿用 chat.py 的流式处理方式）
# ---------------------------------------------------------------------------

def main() -> None:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print(f"本地文件操作 Agent 已启动，工作目录: {BASE_DIR}")
    print("按 Ctrl+C 退出")

    while True:
        try:
            prompt = input("请输入提示词: ")

            print("---")

            messages.append({"role": "user", "content": prompt})

            while True:
                stream = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    tools=tools,
                    stream=True,
                )

                reply = ""
                pending_tool_calls = {}

                for chunk in stream:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta
                    if delta is None:
                        continue

                    if delta.content:
                        reply += delta.content
                        print(delta.content, end="", flush=True)

                    for tc in delta.tool_calls or []:
                        slot = pending_tool_calls.setdefault(
                            tc.index, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function and tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            slot["arguments"] += tc.function.arguments

                if not pending_tool_calls:
                    print()
                    if reply:
                        messages.append({"role": "assistant", "content": reply})
                    break

                print()

                tool_calls = [
                    {
                        "id": pending_tool_calls[index]["id"],
                        "type": "function",
                        "function": {
                            "name": pending_tool_calls[index]["name"],
                            "arguments": pending_tool_calls[index]["arguments"],
                        },
                    }
                    for index in sorted(pending_tool_calls)
                ]

                messages.append(
                    {
                        "role": "assistant",
                        "content": reply or None,
                        "tool_calls": tool_calls,
                    }
                )

                messages.extend(handle_tool_calls(tool_calls))
        except (KeyboardInterrupt, EOFError):
            print("\n再见")
            break


if __name__ == "__main__":
    main()
