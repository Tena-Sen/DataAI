from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence
from urllib.parse import quote, urlencode, urlparse

import httpx
import pandas as pd
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from ..settings import PREVIEWABLE_EXTENSIONS, settings
from .sample_catalog import (
    get_sample_dataset,
    list_sample_datasets,
    resolve_sample_files,
)


GENERATED_INDEX_FILENAME = ".deepanalyze_generated.json"
INTERNAL_WORKSPACE_DIRNAME = ".deepanalyze"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def validate_session_id(session_id: str | None) -> str:
    normalized = str(session_id or "default").strip() or "default"
    if (
        normalized in {".", ".."}
        or not SESSION_ID_PATTERN.fullmatch(normalized)
        or normalized.endswith(".")
    ):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    # 登录态下（HTTP 请求链路）强制会话归属：session_id 必须带当前用户前缀
    from .auth import get_current_user

    user = get_current_user()
    if user and not normalized.startswith(f"u{user}__"):
        raise HTTPException(
            status_code=403, detail="Session does not belong to the current user"
        )
    return normalized


def _workspace_base() -> Path:
    base = Path(settings.workspace_base_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_session_workspace(session_id: str) -> str:
    safe_session_id = validate_session_id(session_id)
    workspace_base = _workspace_base()
    session_dir = (workspace_base / safe_session_id).resolve()
    if session_dir.parent != workspace_base:
        raise HTTPException(status_code=400, detail="Invalid session workspace")
    session_dir.mkdir(parents=True, exist_ok=True)
    return str(session_dir)


def _split_session_relative_path(rel_path: str) -> tuple[str, str]:
    normalized = _normalize_generated_rel_path(rel_path)
    if not normalized:
        return "default", ""

    session_id, _, workspace_rel_path = normalized.partition("/")
    return (session_id or "default"), workspace_rel_path


def _build_workspace_transfer_url(rel_path: str, *, download: bool) -> str:
    session_id, workspace_rel_path = _split_session_relative_path(rel_path)
    params = {
        "session_id": session_id,
        "path": workspace_rel_path,
    }
    if download:
        params["download"] = "1"
    return f"/workspace/download?{urlencode(params, quote_via=quote)}"


def _versioned_workspace_transfer_url(url: str, file_path: Path) -> str:
    """为同名文件覆盖生成新的资源 URL，避免浏览器复用旧缓存。"""
    try:
        version = file_path.stat().st_mtime_ns
    except OSError:
        version = 0
    return f"{url}{'&' if '?' in url else '?'}v={version}"


def build_download_url(rel_path: str) -> str:
    return _build_workspace_transfer_url(rel_path, download=True)


def build_preview_url(rel_path: str) -> str:
    return _build_workspace_transfer_url(rel_path, download=False)


def _extract_docx_text(file_path: Path, max_chars: int = 50000) -> str:
    """纯标准库提取 .docx 段落文本（zip + document.xml，无需 python-docx）。

    表格单元格文本用 " | " 连接，段落保留换行。
    """
    import zipfile
    import xml.etree.ElementTree as ET

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(file_path) as archive:
            xml_bytes = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""

    def paragraph_text(paragraph) -> str:
        return "".join(node.text or "" for node in paragraph.iter(f"{{{ns['w']}}}t"))

    lines: list[str] = []
    body = root.find("w:body", ns)
    if body is None:
        return ""
    for child in body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = paragraph_text(child)
            if text.strip():
                lines.append(text)
        elif tag == "tbl":  # 表格：每行单元格以 " | " 连接
            for row in child.findall("w:tr", ns):
                cells = []
                for cell in row.findall("w:tc", ns):
                    cell_text = " ".join(
                        paragraph_text(p) for p in cell.findall("w:p", ns)
                    ).strip()
                    cells.append(cell_text)
                if any(cells):
                    lines.append(" | ".join(cells))
    content = "\n".join(lines)
    return content[:max_chars]


def _generated_index_path(workspace_root: Path) -> Path:
    return workspace_root / "generated" / GENERATED_INDEX_FILENAME


def _normalize_generated_rel_path(path: str) -> str:
    raw = str(path or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/"):
        return ""
    candidate = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in candidate.parts):
        return ""
    return candidate.as_posix()


def load_generated_index(session_id: str) -> set[str]:
    workspace_root = resolve_workspace_root(session_id)
    index_path = _generated_index_path(workspace_root)
    if not index_path.exists():
        return set()
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(payload, list):
        return set()
    normalized = {
        _normalize_generated_rel_path(str(item))
        for item in payload
        if str(item).strip()
    }
    existing: set[str] = set()
    for rel_path in normalized:
        candidate = workspace_root / rel_path
        if candidate.exists() and candidate.is_file():
            existing.add(rel_path)
    if existing != normalized:
        save_generated_index(session_id, existing)
    return existing


def save_generated_index(session_id: str, rel_paths: Iterable[str]) -> None:
    workspace_root = resolve_workspace_root(session_id)
    index_path = _generated_index_path(workspace_root)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = sorted(
        {
            _normalize_generated_rel_path(str(path))
            for path in rel_paths
            if _normalize_generated_rel_path(str(path))
        }
    )
    index_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_generated_paths(session_id: str, rel_paths: Iterable[str]) -> set[str]:
    generated = load_generated_index(session_id)
    generated.update(
        _normalize_generated_rel_path(str(path))
        for path in rel_paths
        if _normalize_generated_rel_path(str(path))
    )
    save_generated_index(session_id, generated)
    return generated


def unregister_generated_paths(
    session_id: str, rel_paths: Iterable[str], *, prefix: str = ""
) -> None:
    """从生成索引移除条目（用户删除文件/目录时调用）。

    不清理会导致：删除分析产物 csv 后重传同名文件（作为新数据源），
    语义层仍按旧索引排除它。prefix 用于目录删除（移除该目录下所有条目）。
    """
    current = load_generated_index(session_id)
    removed = {
        _normalize_generated_rel_path(str(path))
        for path in rel_paths
        if _normalize_generated_rel_path(str(path))
    }
    prefix_normalized = _normalize_generated_rel_path(prefix)
    remaining = {
        path
        for path in current
        if path not in removed
        and not (prefix_normalized and path.startswith(prefix_normalized + "/"))
    }
    if remaining != current:
        save_generated_index(session_id, remaining)


def collect_file_info(source: str | Path | Sequence[str | Path]) -> str:
    file_paths: list[Path] = []
    seen: set[Path] = set()

    if isinstance(source, (str, Path)):
        candidate = Path(source)
        if not candidate.exists():
            return ""
        if candidate.is_dir():
            file_paths = sorted(
                [
                    path
                    for path in candidate.iterdir()
                    if path.is_file() and path.name != GENERATED_INDEX_FILENAME
                ],
                key=lambda path: path.name.lower(),
            )
        elif candidate.is_file():
            if candidate.name == GENERATED_INDEX_FILENAME:
                return ""
            file_paths = [candidate]
    else:
        for item in source or []:
            candidate = Path(item)
            if (
                not candidate.exists()
                or not candidate.is_file()
                or candidate.name == GENERATED_INDEX_FILENAME
            ):
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            file_paths.append(candidate)
        file_paths.sort(key=lambda path: path.name.lower())

    parts: list[str] = []
    for index, file_path in enumerate(file_paths, start=1):
        size_str = f"{file_path.stat().st_size / 1024:.1f}KB"
        file_info = {"name": file_path.name, "size": size_str}
        parts.append(f"File {index}:\n{json.dumps(file_info, indent=4, ensure_ascii=False)}\n")
    return "\n".join(parts)


def get_file_icon(extension: str) -> str:
    ext = extension.lower()
    icons = {
        (".jpg", ".jpeg", ".png", ".gif", ".bmp"): "🖼️",
        (".pdf",): "📃",
        (".doc", ".docx"): "📌",
        (".txt",): "📝",
        (".md",): "📑",
        (".csv", ".xlsx"): "📳",
        (".json", ".sqlite"): "🗽",
        (".mp4", ".avi", ".mov"): "🎴",
        (".mp3", ".wav"): "🎍",
        (".zip", ".rar", ".tar"): "🗞️",
    }
    for extensions, icon in icons.items():
        if ext in extensions:
            return icon
    return "📧"


TABLE_EXTENSIONS = {
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".parquet",
    ".sqlite",
    ".db",
}

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
}

TEXT_PREVIEW_EXTENSIONS = {
    ".txt",
    ".log",
    ".py",
    ".sql",
    ".json",
    ".yaml",
    ".yml",
}

MARKDOWN_PREVIEW_EXTENSIONS = {
    ".md",
    ".markdown",
}

SQLITE_PREVIEW_EXTENSIONS = {
    ".sqlite",
    ".db",
}

BLOCKED_UPLOAD_EXTENSIONS = {
    ".py",
}


def classify_file_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TABLE_EXTENSIONS:
        return "table"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return "other"


def _json_safe_value(value):
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    return text if len(text) <= 500 else f"{text[:500]}…"


def _build_dataframe_preview(
    dataframe: pd.DataFrame,
    *,
    title: str | None = None,
    kind: str = "table",
    max_rows: int = 100,
    max_cols: int = 30,
    extra: dict | None = None,
) -> dict:
    trimmed = dataframe.copy()
    total_rows = int(len(trimmed.index))
    total_cols = int(len(trimmed.columns))
    if total_cols > max_cols:
        trimmed = trimmed.iloc[:, :max_cols]
    row_truncated = total_rows > max_rows
    col_truncated = total_cols > max_cols
    trimmed = trimmed.head(max_rows).fillna("")
    rows = [
        [_json_safe_value(value) for value in row]
        for row in trimmed.astype(object).values.tolist()
    ]
    payload = {
        "kind": kind,
        "title": title,
        "columns": [str(column) for column in trimmed.columns.tolist()],
        "rows": rows,
        "row_count": total_rows,
        "column_count": total_cols,
        "truncated": row_truncated or col_truncated,
    }
    if extra:
        payload.update(extra)
    return payload


def _clamp_page(page: int, page_size: int) -> tuple[int, int]:
    safe_page_size = max(1, min(page_size, 200))
    safe_page = max(1, page)
    return safe_page, safe_page_size


def _build_paginated_preview(
    dataframe: pd.DataFrame,
    *,
    title: str | None = None,
    kind: str = "table",
    page: int = 1,
    page_size: int = 50,
    max_cols: int = 30,
    extra: dict | None = None,
) -> dict:
    safe_page, safe_page_size = _clamp_page(page, page_size)
    total_rows = int(len(dataframe.index))
    total_cols = int(len(dataframe.columns))
    total_pages = max(1, (total_rows + safe_page_size - 1) // safe_page_size)
    safe_page = min(safe_page, total_pages)

    trimmed = dataframe.copy()
    if total_cols > max_cols:
        trimmed = trimmed.iloc[:, :max_cols]

    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    page_df = trimmed.iloc[start:end].fillna("")
    rows = [
        [_json_safe_value(value) for value in row]
        for row in page_df.astype(object).values.tolist()
    ]
    payload = {
        "kind": kind,
        "title": title,
        "columns": [str(column) for column in page_df.columns.tolist()],
        "rows": rows,
        "row_count": total_rows,
        "column_count": total_cols,
        "page": safe_page,
        "page_size": safe_page_size,
        "total_pages": total_pages,
        "truncated": total_cols > max_cols,
    }
    if extra:
        payload.update(extra)
    return payload


def preview_workspace_file(
    session_id: str,
    relative_path: str,
    *,
    page: int = 1,
    page_size: int = 50,
    table_name: str = "",
    sheet_name: str = "",
) -> dict:
    file_path = resolve_user_workspace_path(session_id, relative_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    ext = file_path.suffix.lower()

    if ext in TEXT_PREVIEW_EXTENSIONS:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return {
            "kind": "text",
            "title": file_path.name,
            "content": content[:50000],
            "truncated": len(content) > 50000,
        }

    if ext in MARKDOWN_PREVIEW_EXTENSIONS:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return {
            "kind": "markdown",
            "title": file_path.name,
            "content": content[:50000],
            "truncated": len(content) > 50000,
        }

    if ext == ".docx":
        # Word 文档：纯标准库提取段落/表格文本（.doc 老二进制格式仍走下载）
        content = _extract_docx_text(file_path)
        if content:
            return {
                "kind": "text",
                "title": file_path.name,
                "content": content,
                "truncated": len(content) >= 50000,
            }
        raise HTTPException(
            status_code=415,
            detail="docx text extraction failed; download to view",
        )

    if ext in {".csv", ".tsv"}:
        separator = "\t" if ext == ".tsv" else ","
        dataframe = pd.read_csv(file_path, sep=separator)
        return _build_paginated_preview(
            dataframe,
            title=file_path.name,
            page=page,
            page_size=page_size,
        )

    if ext in {".xlsx", ".xls"}:
        # 上下文管理器确保关闭底层句柄：ExcelFile 不关闭会一直占用文件，
        # Windows 上导致后续删除报 WinError 32（文件被占用）
        with pd.ExcelFile(file_path) as workbook:
            active_sheet = sheet_name or workbook.sheet_names[0]
            if active_sheet not in workbook.sheet_names:
                raise HTTPException(status_code=404, detail="Sheet not found")
            dataframe = workbook.parse(sheet_name=active_sheet)
            sheet_names = list(workbook.sheet_names)
        return _build_paginated_preview(
            dataframe,
            title=file_path.name,
            page=page,
            page_size=page_size,
            extra={
                "sheet_name": active_sheet,
                "sheet_names": sheet_names,
            },
        )

    if ext in SQLITE_PREVIEW_EXTENSIONS:
        # sqlite3's context manager only manages transactions, not the
        # connection: use closing() so previews don't leak file handles
        # (which also blocks deleting the .db file on Windows).
        with closing(sqlite3.connect(file_path)) as connection:
            cursor = connection.cursor()
            table_names = [
                row[0]
                for row in cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            if not table_name:
                tables: list[dict] = []
                for current_table in table_names:
                    total_rows = cursor.execute(
                        f'SELECT COUNT(*) FROM "{current_table.replace(chr(34), chr(34) * 2)}"'
                    ).fetchone()[0]
                    columns = [
                        row[1]
                        for row in cursor.execute(
                            f'PRAGMA table_info("{current_table.replace(chr(34), chr(34) * 2)}")'
                        ).fetchall()
                    ]
                    tables.append(
                        {
                            "table_name": current_table,
                            "title": current_table,
                            "row_count": int(total_rows),
                            "column_count": len(columns),
                            "columns": columns,
                        }
                    )

                return {
                    "kind": "database",
                    "view": "tables",
                    "title": file_path.name,
                    "tables": tables,
                    "table_names": table_names,
                }

            if table_name not in table_names:
                raise HTTPException(status_code=404, detail="Table not found")

            safe_table_name = table_name.replace('"', '""')
            dataframe = pd.read_sql_query(
                f'SELECT * FROM "{safe_table_name}"',
                connection,
            )
            preview = _build_paginated_preview(
                dataframe,
                title=file_path.name,
                kind="database",
                page=page,
                page_size=page_size,
                extra={
                    "view": "table",
                    "table_name": table_name,
                    "table_names": table_names,
                },
            )
            preview["total_rows"] = preview["row_count"]
            return preview

    raise HTTPException(status_code=415, detail="Preview not supported")


def get_workspace_file_response(
    session_id: str,
    relative_path: str,
    *,
    download: bool = False,
) -> FileResponse:
    file_path = resolve_user_workspace_path(session_id, relative_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    response_kwargs = {
        "path": file_path,
        "content_disposition_type": "attachment" if download else "inline",
    }
    if download:
        response_kwargs["filename"] = file_path.name
    return FileResponse(**response_kwargs)


def uniquify_path(target: Path) -> Path:
    if not target.exists():
        return target

    parent = target.parent
    stem = target.stem
    suffix = target.suffix
    match = re.match(r"^(.*) \((\d+)\)$", stem)
    base = stem
    start = 1
    if match:
        base = match.group(1)
        try:
            start = int(match.group(2)) + 1
        except ValueError:
            start = 1

    index = start
    while True:
        candidate = parent / f"{base} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def resolve_workspace_root(session_id: str) -> Path:
    return Path(get_session_workspace(session_id)).resolve()


def resolve_workspace_path(session_id: str, relative_path: str = "") -> Path:
    workspace_root = resolve_workspace_root(session_id)
    target = (workspace_root / (relative_path or "")).resolve()
    if target != workspace_root and workspace_root not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid path")
    return target


def resolve_user_workspace_path(session_id: str, relative_path: str = "") -> Path:
    workspace_root = resolve_workspace_root(session_id)
    target = resolve_workspace_path(session_id, relative_path)
    if target != workspace_root and is_internal_workspace_path(target, workspace_root):
        raise HTTPException(status_code=400, detail="Internal workspace path is not accessible")
    return target


def is_internal_workspace_path(path: Path, workspace_root: Path | None = None) -> bool:
    candidate = path
    if workspace_root is not None:
        try:
            candidate = path.resolve().relative_to(workspace_root.resolve())
        except (OSError, ValueError):
            return True
    return (
        path.name == GENERATED_INDEX_FILENAME
        or INTERNAL_WORKSPACE_DIRNAME in candidate.parts
    )


def _is_generated_workspace_path(rel_path: str, generated_index: set[str]) -> bool:
    normalized = _normalize_generated_rel_path(rel_path)
    return normalized in generated_index or normalized == "generated" or normalized.startswith("generated/")


def list_workspace_files(session_id: str) -> list[dict]:
    workspace_root = resolve_workspace_root(session_id)
    generated_index = load_generated_index(session_id)
    files: list[dict] = []
    all_files = [
        path
        for path in workspace_root.rglob("*")
        if path.is_file() and not is_internal_workspace_path(path, workspace_root)
    ]
    for file_path in sorted(all_files, key=lambda path: _rel_path(path, workspace_root).lower()):
        rel = _rel_path(file_path, workspace_root)
        rel_path = f"{session_id}/{rel}"
        files.append(
            {
                "name": file_path.name,
                "path": rel,
                "size": file_path.stat().st_size,
                "modified_at_ns": file_path.stat().st_mtime_ns,
                "extension": file_path.suffix.lower(),
                "icon": get_file_icon(file_path.suffix),
                "category": classify_file_type(file_path),
                "is_generated": _is_generated_workspace_path(rel, generated_index),
                "download_url": _versioned_workspace_transfer_url(build_download_url(rel_path), file_path),
                "preview_url": (
                    _versioned_workspace_transfer_url(build_preview_url(rel_path), file_path)
                    if file_path.suffix.lower() in PREVIEWABLE_EXTENSIONS
                    else None
                ),
            }
        )
    return files


def download_generated_bundle(session_id: str, category: str = "all") -> FileResponse:
    workspace_root = resolve_workspace_root(session_id)
    generated_root = workspace_root / "generated"
    if not generated_root.exists() or not generated_root.is_dir():
        raise HTTPException(status_code=404, detail="generated folder not found")

    normalized_category = (category or "all").strip().lower()
    if normalized_category not in {"all", "table", "image", "other"}:
        raise HTTPException(status_code=400, detail="invalid category")

    files = [
        path
        for path in generated_root.rglob("*")
        if path.is_file() and not is_internal_workspace_path(path, workspace_root)
    ]
    if normalized_category != "all":
        files = [
            path for path in files if classify_file_type(path) == normalized_category
        ]

    if not files:
        raise HTTPException(status_code=404, detail="no files matched the category")

    temp_file = tempfile.NamedTemporaryFile(
        prefix=f"deepanalyze_{normalized_category}_",
        suffix=".zip",
        delete=False,
    )
    temp_path = Path(temp_file.name)
    temp_file.close()

    category_dirs = {
        "table": "tables",
        "image": "images",
        "other": "others",
    }

    with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            archive_name = file_path.relative_to(generated_root)
            if normalized_category == "all":
                classified = classify_file_type(file_path)
                archive_name = Path(category_dirs[classified]) / archive_name
            archive.write(file_path, archive_name.as_posix())

    filename = f"generated_{normalized_category}.zip"
    return FileResponse(
        path=temp_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda: temp_path.unlink(missing_ok=True)),
    )


def _rel_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return path.name


def build_tree(
    path: Path,
    root: Path | None = None,
    session_id: str = "default",
    generated_index: set[str] | None = None,
) -> dict:
    root = root or path
    generated_index = generated_index if generated_index is not None else load_generated_index(session_id)
    node: dict = {
        "name": path.name or "workspace",
        "path": _rel_path(path, root),
        "is_dir": path.is_dir(),
    }

    if path.is_dir():
        def sort_key(candidate: Path) -> tuple[bool, bool, str]:
            return (candidate.name == "generated", not candidate.is_dir(), candidate.name.lower())

        node["children"] = [
            build_tree(child, root, session_id, generated_index)
            for child in sorted(path.iterdir(), key=sort_key)
            if not child.name.startswith(".") and not is_internal_workspace_path(child, root)
        ]
        node["is_generated"] = node["path"] == "generated" or node["path"].startswith("generated/")
        return node

    rel = _rel_path(path, root)
    node["size"] = path.stat().st_size
    node["modified_at_ns"] = path.stat().st_mtime_ns
    node["extension"] = path.suffix.lower()
    node["icon"] = get_file_icon(path.suffix)
    node["is_generated"] = _is_generated_workspace_path(rel, generated_index)
    node["download_url"] = _versioned_workspace_transfer_url(
        build_download_url(f"{session_id}/{rel}"), path
    )
    if path.suffix.lower() in PREVIEWABLE_EXTENSIONS:
        node["preview_url"] = _versioned_workspace_transfer_url(
            build_preview_url(f"{session_id}/{rel}"), path
        )
    return node


def delete_workspace_file(session_id: str, relative_path: str) -> dict:
    target = resolve_user_workspace_path(session_id, relative_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Folder deletion not allowed")
    rel_posix = (
        target.resolve().relative_to(resolve_workspace_root(session_id)).as_posix()
    )
    target.unlink()
    # 同步清理生成索引：否则删除产物后重传同名文件会被语义层继续排除
    unregister_generated_paths(session_id, [rel_posix])
    return {"message": "deleted"}


def move_workspace_path(session_id: str, src: str, dst_dir: str = "") -> dict:
    source = resolve_user_workspace_path(session_id, src)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source not found")

    target_dir = resolve_user_workspace_path(session_id, dst_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = uniquify_path(target_dir / source.name)
    shutil.move(str(source), str(target))
    return {
        "message": "moved",
        "new_path": target.relative_to(resolve_workspace_root(session_id)).as_posix(),
    }


def delete_workspace_dir(session_id: str, relative_path: str, recursive: bool = True) -> dict:
    workspace_root = resolve_workspace_root(session_id)
    target = resolve_user_workspace_path(session_id, relative_path)
    if target == workspace_root:
        raise HTTPException(status_code=400, detail="Cannot delete workspace root")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")
    rel_posix = target.resolve().relative_to(workspace_root).as_posix()
    if recursive:
        shutil.rmtree(target)
    else:
        target.rmdir()
    # 目录删除：清理该目录下所有生成索引条目
    unregister_generated_paths(session_id, [], prefix=rel_posix)
    return {"message": "deleted"}


_PROXY_MAX_BYTES = 10 * 1024 * 1024


async def proxy_external_file(url: str) -> Response:
    # Off by default: an open proxy is an SSRF hole (internal endpoints,
    # cloud metadata services). Enable only via DEEPANALYZE_ENABLE_EXTERNAL_PROXY.
    if not settings.enable_external_proxy:
        raise HTTPException(status_code=403, detail="External proxy is disabled")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Only http/https URLs are allowed")
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            async with client.stream("GET", url) as response:
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > _PROXY_MAX_BYTES:
                        raise HTTPException(
                            status_code=502, detail="Proxied file too large"
                        )
                    chunks.append(chunk)
                content = b"".join(chunks)
                media_type = response.headers.get(
                    "content-type", "application/octet-stream"
                )
                status_code = response.status_code
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Proxy fetch failed: {exc}") from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={"Access-Control-Allow-Origin": "*"},
        status_code=status_code,
    )


async def _save_uploads(
    workspace_root: Path,
    target_dir: Path,
    files: Iterable[UploadFile],
) -> tuple[list[dict], list[str]]:
    def workspace_usage() -> tuple[int, int]:
        existing_files = [
            path
            for path in workspace_root.rglob("*")
            if path.is_file() and not is_internal_workspace_path(path, workspace_root)
        ]
        return len(existing_files), sum(path.stat().st_size for path in existing_files)

    def safe_upload_filename(raw_name: str | None) -> str:
        raw = str(raw_name or "untitled").strip()
        normalized = raw.replace("\\", "/")
        name = PurePosixPath(normalized).name
        stem_upper = Path(name).stem.upper()
        if (
            not name
            or name in {".", ".."}
            or normalized != name
            or name.endswith((" ", "."))
            or stem_upper in WINDOWS_RESERVED_NAMES
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
        ):
            raise HTTPException(status_code=400, detail="Invalid upload filename")
        return name

    saved: list[dict] = []
    rejected: list[str] = []
    file_count, workspace_bytes = workspace_usage()
    for file in files:
        filename = safe_upload_filename(file.filename)
        ext = Path(filename).suffix.lower()
        if ext in BLOCKED_UPLOAD_EXTENSIONS:
            rejected.append(filename)
            continue
        if file_count >= settings.workspace_max_files:
            raise HTTPException(status_code=413, detail="Workspace file count limit exceeded")

        dst = uniquify_path(target_dir / filename)
        temp_file = tempfile.NamedTemporaryFile(
            prefix=".deepanalyze-upload-",
            suffix=".tmp",
            dir=target_dir,
            delete=False,
        )
        temp_path = Path(temp_file.name)
        uploaded_bytes = 0
        try:
            with temp_file:
                while True:
                    chunk = await file.read(settings.upload_chunk_bytes)
                    if not chunk:
                        break
                    uploaded_bytes += len(chunk)
                    if uploaded_bytes > settings.upload_max_file_bytes:
                        raise HTTPException(status_code=413, detail="Upload file size limit exceeded")
                    if workspace_bytes + uploaded_bytes > settings.workspace_max_bytes:
                        raise HTTPException(status_code=413, detail="Workspace size limit exceeded")
                    temp_file.write(chunk)
            temp_path.replace(dst)
        finally:
            temp_path.unlink(missing_ok=True)

        file_count += 1
        workspace_bytes += uploaded_bytes
        saved.append(
            {
                "name": dst.name,
                "size": uploaded_bytes,
                "path": dst.relative_to(workspace_root).as_posix(),
            }
        )
    return saved, rejected


async def upload_files_to_workspace(session_id: str, files: Iterable[UploadFile]) -> dict:
    workspace_root = resolve_workspace_root(session_id)
    saved, rejected = await _save_uploads(workspace_root, workspace_root, files)
    return {
        "message": f"Successfully uploaded {len(saved)} files",
        "files": saved,
        "rejected": rejected,
    }


def get_sample_catalog() -> dict:
    return {"datasets": list_sample_datasets()}


def create_sample_data(
    session_id: str,
    sample_id: str,
    *,
    clear_existing: bool = False,
) -> dict:
    """Copy a cataloged public dataset into the current session workspace."""
    dataset = get_sample_dataset(sample_id)
    sources = resolve_sample_files(dataset)
    workspace_root = resolve_workspace_root(session_id)

    if clear_existing:
        source_sizes = [source.stat().st_size for source in sources]
        if any(size > settings.upload_max_file_bytes for size in source_sizes):
            raise HTTPException(status_code=413, detail="Sample file size limit exceeded")
        if len(sources) > settings.workspace_max_files:
            raise HTTPException(status_code=413, detail="Workspace file count limit exceeded")
        if sum(source_sizes) > settings.workspace_max_bytes:
            raise HTTPException(status_code=413, detail="Workspace size limit exceeded")
        clear_workspace(session_id)

    existing_files = [
        path
        for path in workspace_root.rglob("*")
        if path.is_file() and not is_internal_workspace_path(path, workspace_root)
    ]
    file_count = len(existing_files)
    workspace_bytes = sum(path.stat().st_size for path in existing_files)
    loaded_paths: list[str] = []

    for source in sources:
        source_size = source.stat().st_size
        if source_size > settings.upload_max_file_bytes:
            raise HTTPException(status_code=413, detail="Sample file size limit exceeded")

        target = workspace_root / source.name
        numbered_name = re.compile(
            rf"^{re.escape(source.stem)} \(\d+\){re.escape(source.suffix)}$"
        )
        reusable_targets = [
            path
            for path in workspace_root.iterdir()
            if path.is_file()
            and (path.name == source.name or numbered_name.fullmatch(path.name))
        ]
        reused = next(
            (
                path
                for path in reusable_targets
                if path.stat().st_size == source_size
                and path.read_bytes() == source.read_bytes()
            ),
            None,
        )
        if reused is not None:
            loaded_paths.append(reused.relative_to(workspace_root).as_posix())
            continue
        target = uniquify_path(target)

        if file_count >= settings.workspace_max_files:
            raise HTTPException(status_code=413, detail="Workspace file count limit exceeded")
        if workspace_bytes + source_size > settings.workspace_max_bytes:
            raise HTTPException(status_code=413, detail="Workspace size limit exceeded")

        shutil.copy2(source, target)
        file_count += 1
        workspace_bytes += source_size
        loaded_paths.append(target.relative_to(workspace_root).as_posix())

    files_by_path = {item["path"]: item for item in list_workspace_files(session_id)}
    return {
        "message": "Sample data is ready",
        "sample_id": dataset["id"],
        "workspace_cleared": clear_existing,
        "files": [files_by_path[path] for path in loaded_paths],
    }


async def upload_files_to_dir(session_id: str, directory: str, files: Iterable[UploadFile]) -> dict:
    workspace_root = resolve_workspace_root(session_id)
    target_dir = resolve_user_workspace_path(session_id, directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    saved, rejected = await _save_uploads(workspace_root, target_dir, files)
    return {"message": f"uploaded {len(saved)}", "files": saved, "rejected": rejected}


def clear_workspace(session_id: str) -> dict:
    workspace_root = resolve_workspace_root(session_id)
    for child in workspace_root.iterdir():
        if child.name == INTERNAL_WORKSPACE_DIRNAME:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    return {"message": "Workspace cleared successfully"}
