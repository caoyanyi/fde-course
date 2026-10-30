from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

from defusedxml import ElementTree


ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".py", ".php", ".js", ".ts", ".tsx", ".jsx", ".vue", ".json", ".csv",
    ".yaml", ".yml", ".sql", ".sh", ".html", ".css", ".log", ".pdf", ".docx",
}
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_FILES = 5
MAX_EXTRACTED_CHARS = 30_000


def safe_filename(name: str) -> str:
    # Keep a readable display name but never use it as a storage path.
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    if not name or len(name) > 180:
        raise ValueError("文件名为空或超过 180 字符")
    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("不支持该文件扩展名，请上传说明中列出的文本、PDF 或 DOCX 文件")
    return name


def extract_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 300 or sum(entry.file_size for entry in entries) > 10 * 1024 * 1024:
                raise ValueError("DOCX 解压后过大或包含过多条目")
            document = archive.getinfo("word/document.xml")
            if document.file_size > 2 * 1024 * 1024:
                raise ValueError("DOCX 正文过大")
            root = ElementTree.fromstring(archive.read(document))
            paragraphs = []
            for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                paragraphs.append("".join(paragraph.itertext()))
            return "\n".join(paragraphs)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError, NotImplementedError, EOFError) as exc:
        raise ValueError("DOCX 文件损坏或格式无效") from exc


def extract_file(path: Path, filename: str, data: bytes) -> tuple[str, bool, str, list[dict]]:
    extension = Path(filename).suffix.lower()
    checks: list[dict] = []
    note = "仅提取文本，不执行文件中的代码或命令。"
    truncated = False
    try:
        if extension == ".docx":
            text = extract_docx(data)
            note = "仅提取 DOCX 正文文本，不包含图片、批注或附件。"
        elif extension == ".pdf":
            # PDF is untrusted parser input. A dedicated process has CPU/memory limits;
            # its only operation is text extraction. User code is never imported/run.
            result = subprocess.run(
                [sys.executable, "-m", "app.extract_pdf", str(path)],
                capture_output=True, text=True, timeout=15, check=False,
            )
            if result.returncode != 0:
                raise ValueError("PDF 无法安全提取文本；请改为文本/Markdown，或上传未加密的文字版 PDF")
            payload = json.loads(result.stdout)
            text, truncated = payload["text"], payload["truncated"]
            note = "仅提取前 30 页可复制文本；扫描件图片不做 OCR。"
        else:
            if b"\x00" in data:
                raise ValueError("文本附件包含二进制内容，请转换成 UTF-8 文本")
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError("文本附件必须使用 UTF-8 编码") from exc
            if extension == ".json":
                try:
                    json.loads(text)
                    checks.append({"name": f"{filename} · JSON 语法", "status": "passed", "message": "JSON 可以解析；未验证业务正确性。"})
                except (ValueError, RecursionError):
                    checks.append({"name": f"{filename} · JSON 语法", "status": "failed", "message": "JSON 语法不合法或嵌套过深。"})
            elif extension == ".py":
                try:
                    ast.parse(text, filename=filename)
                    checks.append({"name": f"{filename} · Python 语法", "status": "passed", "message": "Python AST 解析通过；没有执行代码、导入依赖或运行测试。"})
                except (SyntaxError, ValueError, RecursionError, MemoryError):
                    checks.append({"name": f"{filename} · Python 语法", "status": "failed", "message": "Python 语法解析失败；没有执行代码。"})
    except subprocess.TimeoutExpired as exc:
        raise ValueError("PDF 文本提取超时，请改用 Markdown 或纯文本") from exc
    except (ValueError, KeyError) as exc:
        raise ValueError(str(exc)) from exc
    truncated = truncated or len(text) > MAX_EXTRACTED_CHARS
    text = text[:MAX_EXTRACTED_CHARS]
    if truncated:
        note += f" AI 仅能读取前 {MAX_EXTRACTED_CHARS} 字符。"
    if not text.strip():
        checks.append({"name": f"{filename} · 可读证据", "status": "warning", "message": "未提取到可读文本；AI 无法验证图片或扫描内容。"})
    return text, truncated, note, checks


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
