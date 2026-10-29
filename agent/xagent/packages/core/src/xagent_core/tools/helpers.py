"""文件工具使用的公共辅助函数。

这里只放与具体工具无关的路径、文本和 JSON 协议逻辑，保持工具实现代码简洁。
"""

from __future__ import annotations

import json
import mimetypes
import os
import stat
from pathlib import Path

from .base import ToolContext

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


def ok(**data: object) -> str:
    """构造成功结果（统一 JSON 协议）。"""

    return json.dumps({"success": True, **data}, ensure_ascii=False, indent=2)


def fail(message: str, **data: object) -> str:
    """构造失败结果（统一 JSON 协议）。"""

    return json.dumps(
        {"success": False, "error": message, **data},
        ensure_ascii=False,
        indent=2,
    )


def resolve_path(context: ToolContext, raw: object) -> Path:
    """把模型传入的路径解析为绝对路径，相对路径基于当前工作目录。"""

    text = str(raw if raw is not None else "").strip().strip('"').strip("'")
    if not text:
        raise ValueError("路径不能为空")
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    if not path.is_absolute():
        path = context.base_dir / path
    return path.resolve()


def is_protected(context: ToolContext, path: Path) -> str | None:
    """判断路径是否属于禁止删除/覆盖的高危目录。"""

    if path == path.parent:
        return "拒绝操作磁盘根目录"
    if path == context.base_dir:
        return "拒绝操作当前工作目录本身"
    if path == Path.home().resolve():
        return "拒绝操作用户主目录"
    if path in context.base_dir.parents:
        return "拒绝操作当前工作目录的上级目录"
    return None


def decode_text(raw: bytes) -> tuple[str | None, str | None]:
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


def is_text_file(path: Path) -> bool:
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
        with open(path, "rb") as handle:
            head = handle.read(8192)
    except OSError:
        return False
    text, _ = decode_text(head)
    return text is not None


def read_text(path: Path) -> tuple[str, str]:
    """读取纯文本文件，返回 (文本, 编码)。"""

    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("该文件包含二进制内容，不是纯文本文件")
    text, encoding = decode_text(raw)
    if text is None:
        raise ValueError("无法按 UTF-8 / GB18030 解码该文件，可能不是纯文本文件")
    return text, encoding or "unknown"


def write_text(path: Path, text: str) -> None:
    """以 UTF-8 + LF 写入文本，保证跨平台行为一致。"""

    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def append_text(path: Path, text: str) -> None:
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def on_rm_error(func, path, exc_info) -> None:
    """删除只读文件时先去掉只读属性再重试。"""

    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def positive_int(value: object, default: int, maximum: int) -> int:
    """把模型传入的整数参数限制在 (0, maximum] 范围内。"""

    if value is None or value == "":
        return default
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    return min(number, maximum)


def as_bool(value: object, default: bool = False) -> bool:
    """把模型传入的布尔值做一次严格解析，避免 bool("false") 为 True。"""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)
