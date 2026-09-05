"""Session 语义层自动构建：上传数据 → DuckDB + 动态 MDL。

把 session workspace 里的表格文件（CSV / Excel）自动导入 DuckDB 并生成
WrenAI MDL，使模型能通过 wren_query() 用 SQL 分析上传数据：
  - 引擎目录：workspace/<session>/.deepanalyze/wren/
  - catalog 名 = duckdb 文件名（wren duckdb connector 按文件名 attach）
  - 表名/列名沿用原文件（清理为合法标识符，中文保留）
指纹缓存：上传文件 (size, mtime_ns) 集合不变则不重建。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from .workspace import get_session_workspace
from ..settings import settings

DATA_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls"}
CATALOG_NAME = "session_data"
SEMANTIC_DIRNAME = "wren"
_MAX_SHEETS_PER_FILE = 20
_MAX_COLUMNS_PER_TABLE = 200

_BUILD_LOCKS: dict[str, threading.Lock] = {}
_BUILD_LOCKS_GUARD = threading.Lock()
_LAYER_CACHE: dict[str, tuple[str, "SemanticLayer"]] = {}


@dataclass
class SemanticLayer:
    """session 语义层产物：文件路径 + 模型清单（供提示词注入）。"""

    dir: str
    mdl_path: str
    conn_path: str
    models: list[dict]
    relationships: list[dict] = field(default_factory=list)


def semantic_layer_dir(session_id: str) -> Path:
    workspace = Path(get_session_workspace(session_id))
    return workspace / ".deepanalyze" / SEMANTIC_DIRNAME


def _session_lock(session_id: str) -> threading.Lock:
    with _BUILD_LOCKS_GUARD:
        lock = _BUILD_LOCKS.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _BUILD_LOCKS[session_id] = lock
        return lock


def _clean_identifier(name: object, fallback: str) -> str:
    """清理为 SQL 合法标识符：保留中文/字母/数字/下划线，其余删除。"""
    text = re.sub(r"\s+", "_", str(name or "").strip())
    text = re.sub(r"[^\w]", "", text, flags=re.UNICODE)
    return text or fallback


def _read_tabular(path: Path) -> dict[str, pd.DataFrame]:
    """读表格文件为 {表名: DataFrame}；CSV 编码 utf-8 优先、gbk 兜底。"""
    suffix = path.suffix.lower()
    stem = _clean_identifier(path.stem, "data")
    if suffix in {".csv", ".tsv"}:
        for encoding in ("utf-8", "utf-8-sig", "gbk"):
            try:
                df = pd.read_csv(
                    path,
                    encoding=encoding,
                    sep="\t" if suffix == ".tsv" else ",",
                )
                return {stem: df}
            except (UnicodeDecodeError, UnicodeError):
                continue
        df = pd.read_csv(path, sep=None, engine="python")
        return {stem: df}
    try:
        sheets = pd.read_excel(path, sheet_name=None)
    except Exception:
        return {}
    tables: dict[str, pd.DataFrame] = {}
    for index, (sheet_name, df) in enumerate(sheets.items()):
        if index >= _MAX_SHEETS_PER_FILE or df.empty:
            continue
        sheet_id = _clean_identifier(sheet_name, f"sheet{index + 1}")
        table_name = stem if len(sheets) == 1 else f"{stem}_{sheet_id}"
        tables[table_name] = df
    return tables


def _collect_upload_files(session_id: str, workspace_dir: Path) -> list[Path]:
    """workspace 根目录第一层的**用户上传**表格文件。

    排除两类：generated/ 子目录；以及代码执行生成、已登记到生成索引
    （load_generated_index）的根目录文件（如分析产物 汇总.csv —— 它们是
    分析输出而非数据源，进语义层会污染表清单）。走 load_generated_index
    而非直读 JSON：它对已删除条目自清理，删除产物后重传同名文件可正常入库。
    """
    from .workspace import load_generated_index

    if not workspace_dir.is_dir():
        return []
    generated_index = load_generated_index(session_id)  # 相对 posix 路径集合
    return sorted(
        (
            path
            for path in workspace_dir.iterdir()
            if path.is_file()
            and not path.name.startswith(".")
            and path.suffix.lower() in DATA_EXTENSIONS
            and path.name not in generated_index
        ),
        key=lambda path: path.name.lower(),
    )


def _upload_fingerprint(files: list[Path]) -> str:
    parts = []
    for path in files:
        try:
            stat = path.stat()
            parts.append(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}")
        except OSError:
            continue
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _normalize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """类型规整：数值/时间列保留，混合脏数据列统一降级为字符串。

    真实 Excel 常见单列混杂数字与文本（'5192    28.73%'），duckdb 对这类
    object 列的自动推断会按多数值定型并强转失败；统一转 VARCHAR 最稳。
    """
    for col in df.columns:
        dtype = df[col].dtype
        if pd.api.types.is_numeric_dtype(dtype) or pd.api.types.is_datetime64_any_dtype(dtype):
            continue
        series = df[col]
        if series.isna().any():
            df[col] = (
                series.astype(object)
                .where(series.notna(), None)
                .map(lambda v: v if v is None else str(v))
            )
        else:
            df[col] = series.astype(str)
    return df


def _import_table(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> None:
    if len(df.columns) > _MAX_COLUMNS_PER_TABLE:
        df = df.iloc[:, :_MAX_COLUMNS_PER_TABLE]
    # 列名清洗 + 顺序去重（col/col → col/col_2）
    seen: dict[str, int] = {}
    columns: list[str] = []
    for index, col in enumerate(df.columns):
        base = _clean_identifier(col, "col") or f"col_{index + 1}"
        if base in seen:
            seen[base] += 1
            base = f"{base}_{seen[base] + 1}"
        else:
            seen[base] = 1
        columns.append(base)
    df = df.convert_dtypes()  # 纯数字文本 → 数值；NaN → pd.NA
    df = _normalize_dtypes(df)  # 混合脏列 → VARCHAR，杜绝 duckdb 强转失败
    df.columns = columns
    con.register("_staging_df", df)
    con.execute(f'DROP TABLE IF EXISTS "{table}"')
    con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM _staging_df')
    con.unregister("_staging_df")


def _describe_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[dict]:
    rows = con.execute(f'DESCRIBE "{table}"').fetchall()
    return [
        {
            "name": str(row[0]),
            "type": str(row[1]),
            "isCalculated": False,
            "notNull": False,
            "properties": {},
        }
        for row in rows
    ]


def _row_count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _write_mdl(
    wren_dir: Path, models: list[dict], relationships: list[dict] | None = None
) -> None:
    mdl = {
        "catalog": CATALOG_NAME,
        "schema": "main",
        "models": models,
        "relationships": relationships or [],
        "views": [],
        "cubes": [],
        "dataSource": "duckdb",
        "layoutVersion": 3,
    }
    (wren_dir / "mdl.json").write_text(
        json.dumps(mdl, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _write_conn(wren_dir: Path) -> None:
    # wren duckdb connector：url 指向目录，按 .duckdb 文件名 attach 为同名 catalog
    conn = {
        "datasource": "duckdb",
        "url": str(wren_dir).replace("\\", "/"),
        "format": "duckdb",
    }
    (wren_dir / "conn.json").write_text(
        json.dumps(conn, ensure_ascii=False), encoding="utf-8"
    )


# ---------- 表间关系推断（同名列 + 键列名启发式，写入 MDL relationships） ----------

_MAX_RELATIONSHIPS = 20
_JOIN_KEY_CN_SUFFIXES = ("编号", "编码", "代码", "标识", "识别码", "键", "号")
_JOIN_KEY_ASCII_RE = re.compile(
    r"^(?:(?:[a-z0-9]+_)+(?:id|no|num|number|code|key|uuid|guid)?|"
    r"(id|no|num|number|code|key|uuid|guid))$",
    re.IGNORECASE,
)


def _is_join_key_column(name: str) -> bool:
    """列名是否像关联键：customer_id / 订单编号 / 客户ID / 单号 等。

    同名列 + 键样式双重过滤，避免"金额/日期"这类业务度量被误判为 JOIN 键。
    """
    if _JOIN_KEY_ASCII_RE.match(name):
        return True
    if name.endswith("ID"):  # 中英混排：客户ID / 用户ID（ascii 大写 ID 后缀）
        return True
    return any(name.endswith(suffix) for suffix in _JOIN_KEY_CN_SUFFIXES)


def _infer_relationships(models: list[dict], row_counts: dict[str, int]) -> list[dict]:
    """跨表同名列推断 JOIN 关系（many_to_one：高行数表 → 低行数表）。

    返回 MDL 标准 relationships + 供提示词/前端的摘要（同一 dict，引擎取
    name/models/joinType/condition，提示词取 from_table 等附加字段）。
    """
    # 同名键列 → 出现该列的表集合
    column_tables: dict[str, list[str]] = {}
    for model in models:
        table = model["name"]
        for column in model["columns"]:
            name = column["name"]
            if _is_join_key_column(name):
                column_tables.setdefault(name, []).append(table)

    relationships: list[dict] = []
    for column, tables in sorted(column_tables.items()):
        if len(tables) < 2:
            continue
        # 两两组合（同名列出现在 3+ 表时也只取两两，避免组合爆炸）
        for index in range(len(tables)):
            for jndex in range(index + 1, len(tables)):
                table_a, table_b = tables[index], tables[jndex]
                # 方向：行数多的一侧（事实表）many_to_one 指向行数少的一侧（维表）
                if row_counts.get(table_b, 0) > row_counts.get(table_a, 0):
                    table_a, table_b = table_b, table_a
                relationships.append(
                    {
                        "name": f"{table_a}_{column}__{table_b}",
                        "models": [table_a, table_b],
                        "joinType": "MANY_TO_ONE",
                        "condition": f"{table_a}.{column} = {table_b}.{column}",
                        "from_table": table_a,
                        "from_column": column,
                        "to_table": table_b,
                        "to_column": column,
                    }
                )
                if len(relationships) >= _MAX_RELATIONSHIPS:
                    return relationships
    return relationships


# ---------- 数据字典（列含义，由 AI 编目后写回、后续轮次自动注入） ----------

DICTIONARY_FILENAME = "dictionary.json"
EXCLUDED_FILENAME = "excluded.json"


def _excluded_path(session_id: str) -> Path:
    return semantic_layer_dir(session_id) / EXCLUDED_FILENAME


def load_excluded(session_id: str) -> set[str]:
    """已删除的表名集合（持久化，重建时跳过）。"""
    path = _excluded_path(session_id)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(name) for name in data if str(name).strip()}
    except (OSError, ValueError):
        return set()


def _save_excluded(session_id: str, excluded: set[str]) -> None:
    path = _excluded_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(sorted(excluded), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    tmp.replace(path)


def remove_table(session_id: str, table: str) -> str:
    """从语义层删除表：登记排除清单并立即重建。

    只影响语义层（提示词/查询/预览），原上传文件不动；可经 restore_table 恢复。
    """
    table = str(table or "").strip()
    if not table:
        return "remove failed: empty table name"
    layer = build_semantic_layer(session_id)
    if layer is None:
        return "remove failed: semantic layer unavailable"
    if table not in {model["name"] for model in layer.models}:
        return f"remove failed: unknown table '{table}'"
    with _session_lock(session_id):
        excluded = load_excluded(session_id)
        excluded.add(table)
        _save_excluded(session_id, excluded)
        _LAYER_CACHE.pop(session_id, None)
    return f"removed '{table}' from the semantic layer (restore available)"


def restore_table(session_id: str, table: str) -> str:
    """恢复已删除的表（清除排除标记并重建）。"""
    table = str(table or "").strip()
    if not table:
        return "restore failed: empty table name"
    with _session_lock(session_id):
        excluded = load_excluded(session_id)
        if table not in excluded:
            return f"restore failed: '{table}' is not excluded"
        excluded.discard(table)
        _save_excluded(session_id, excluded)
        _LAYER_CACHE.pop(session_id, None)
    return f"restored '{table}' to the semantic layer"


def data_dictionary_path(session_id: str) -> Path:
    return semantic_layer_dir(session_id) / DICTIONARY_FILENAME


# ---------- 用户级列含义库（跨会话复用） ----------
# session 字典随会话生灭：换个会话重传同一文件，模型要重新编目所有列。
# 全局库按「用户 + 表列签名」持久化列含义，构建语义层时自动回填到
# session 字典（新会话零编目启动），登记时同步写入。

DICTIONARIES_DIRNAME = "dictionaries"
_DICTIONARY_SIG_LOCK = threading.Lock()


def _user_dictionaries_dir(session_id: str) -> Path | None:
    from .auth import resolve_user_from_session

    user = resolve_user_from_session(session_id)
    if not user:
        return None
    base = Path(settings.workspace_base_dir) / MEMORY_BASE_DIRNAME / user / DICTIONARIES_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _table_signature(columns: list[str]) -> str:
    """表的列签名：排序后列名序列的 sha1（文件名/表名不同但同结构的表复用含义）。"""
    joined = "\n".join(sorted(str(c) for c in columns))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def _global_dictionary_path(session_id: str, columns: list[str]) -> Path | None:
    base = _user_dictionaries_dir(session_id)
    if base is None:
        return None
    return base / f"dict_{_table_signature(columns)}.json"


def _sync_to_global_dictionary(session_id: str, table: str, clean: dict[str, str]) -> None:
    """把列含义同步到用户级全局库（按表的列签名；需要该表的列清单）。"""
    try:
        # 从磁盘 MDL 取列清单（不依赖 _LAYER_CACHE：登记时缓存刚被 pop 失效）
        columns: list[str] = []
        mdl_path = semantic_layer_dir(session_id) / "mdl.json"
        try:
            mdl = json.loads(mdl_path.read_text(encoding="utf-8"))
            for model in mdl.get("models") or []:
                if model.get("name") == table:
                    columns = [str(c.get("name")) for c in model.get("columns") or []]
                    break
        except (OSError, ValueError):
            columns = []
        if not columns:
            return
        path = _global_dictionary_path(session_id, columns)
        if path is None:
            return
        with _DICTIONARY_SIG_LOCK:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            entry = data.get(table) or {}
            entry.update(clean)
            data[table] = entry
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            tmp.replace(path)
    except Exception:
        pass  # 全局库同步尽力而为，不影响 session 字典主流程


def _backfill_from_global_dictionary(
    session_id: str, tables: dict[str, pd.DataFrame]
) -> int:
    """session 字典中缺失的表，从用户级全局库按列签名回填。返回回填表数。"""
    session_dict_path = data_dictionary_path(session_id)
    try:
        session_dict = (
            json.loads(session_dict_path.read_text(encoding="utf-8"))
            if session_dict_path.exists()
            else {}
        )
        if not isinstance(session_dict, dict):
            session_dict = {}
    except (OSError, ValueError):
        session_dict = {}

    changed = False
    for table, df in tables.items():
        if session_dict.get(table):
            continue
        path = _global_dictionary_path(session_id, list(df.columns))
        if path is None or not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for _, entry in data.items():
            if isinstance(entry, dict) and entry:
                session_dict[table] = dict(entry)
                changed = True
                break
    if changed:
        session_dict_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = session_dict_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(session_dict, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(session_dict_path)
    return sum(1 for t in tables if session_dict.get(t))


def load_data_dictionary(session_id: str) -> dict[str, dict[str, str]]:
    """{表名: {列名: 含义描述}}；文件缺失/损坏返回空 dict。"""
    path = data_dictionary_path(session_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_column_descriptions(session_id: str, table: str, descriptions: dict) -> str:
    """合并写入列描述（执行子进程调用；原子替换，失败不抛异常）。

    返回状态字符串，便于模型在输出中看到登记结果。
    """
    table = str(table or "").strip()
    if not table:
        return "wren_describe failed: empty table name"
    clean = {
        str(col).strip(): str(desc).strip()
        for col, desc in (descriptions or {}).items()
        if str(col).strip() and str(desc).strip()
    }
    if not clean:
        return f"wren_describe skipped: no valid descriptions for '{table}'"
    path = data_dictionary_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _session_lock(session_id):
        dictionary = load_data_dictionary(session_id)
        table_entry = dictionary.get(table) or {}
        table_entry.update(clean)
        dictionary[table] = table_entry
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(dictionary, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(path)
        # 字典变化使语义层缓存失效（指纹含字典 mtime）
        _LAYER_CACHE.pop(session_id, None)
    # 同步到用户级全局库：其他会话重传同结构文件时自动复用这些列含义
    _sync_to_global_dictionary(session_id, table, clean)
    return f"registered {len(clean)} column descriptions for '{table}'"


def _dictionary_fingerprint(session_id: str) -> float:
    try:
        return data_dictionary_path(session_id).stat().st_mtime
    except OSError:
        return 0.0


def _excluded_fingerprint(session_id: str) -> float:
    try:
        return _excluded_path(session_id).stat().st_mtime
    except OSError:
        return 0.0


def build_semantic_layer(session_id: str) -> SemanticLayer | None:
    """确保 session 语义层为最新；无表格数据时返回 None。

    进程内按指纹缓存；同 session 构建串行化（与上传并发安全）。
    """
    workspace_dir = Path(get_session_workspace(session_id))
    files = _collect_upload_files(session_id, workspace_dir)
    if not files:
        return None
    # 字典/排除清单 mtime 纳入指纹：AI 编目或删表后，下一轮重建生效
    fingerprint = (
        _upload_fingerprint(files)
        + f":{_dictionary_fingerprint(session_id)}"
        + f":{_excluded_fingerprint(session_id)}"
    )

    with _session_lock(session_id):
        cached = _LAYER_CACHE.get(session_id)
        if cached and cached[0] == fingerprint:
            return cached[1]

        # 读取全部表格；单个文件失败跳过（分析仍可走 pandas）；排除清单中的表跳过
        excluded = load_excluded(session_id)
        tables: dict[str, pd.DataFrame] = {}
        source_by_table: dict[str, str] = {}
        for path in files:
            try:
                file_tables = _read_tabular(path)
            except Exception:
                continue
            for table, df in file_tables.items():
                if table in excluded:
                    continue
                unique = table
                suffix = 1
                while unique in tables:
                    suffix += 1
                    unique = f"{table}_{suffix}"
                tables[unique] = df
                source_by_table[unique] = path.name
        if not tables:
            return None

        # 跨会话列含义回填：session 字典缺失的表从用户级全局库按列签名复用
        try:
            _backfill_from_global_dictionary(session_id, tables)
        except Exception:
            pass  # 回填失败不阻断语义层构建

        wren_dir = semantic_layer_dir(session_id)
        wren_dir.mkdir(parents=True, exist_ok=True)
        db_path = wren_dir / f"{CATALOG_NAME}.duckdb"
        tmp_db = wren_dir / f"{CATALOG_NAME}.duckdb.tmp"

        models: list[dict] = []
        model_summaries: list[dict] = []
        # 字典含义需在 build 内先加载：既写进 MDL（引擎侧），也合并进摘要（提示词侧）
        dictionary = load_data_dictionary(session_id)
        con = duckdb.connect(str(tmp_db))
        try:
            for table, df in tables.items():
                _import_table(con, table, df)
                row_count = _row_count(con, table)
                desc_by_col = dictionary.get(table) or {}
                columns = _describe_columns(con, table)
                for column in columns:
                    meaning = desc_by_col.get(column["name"])
                    if meaning:
                        column["properties"]["description"] = meaning
                models.append(
                    {
                        "name": table,
                        "properties": {
                            "description": (
                                f"来自 '{source_by_table[table]}' 的数据（约 {row_count} 行）"
                            )
                        },
                        "tableReference": {
                            "catalog": CATALOG_NAME,
                            "schema": "main",
                            "table": table,
                        },
                        "columns": columns,
                        "cached": False,
                    }
                )
                model_summaries.append(
                    {
                        "name": table,
                        "description": models[-1]["properties"]["description"],
                        "source_file": source_by_table[table],
                        "row_count": row_count,
                        "columns": [
                            {
                                "name": c["name"],
                                "type": c["type"],
                                **({"desc": c["properties"]["description"]} if c["properties"].get("description") else {}),
                            }
                            for c in columns
                        ],
                    }
                )
        finally:
            con.close()

        # 表间关系推断（同名列 + 键样式）：写入 MDL 供引擎使用，同时进提示词摘要
        row_counts = {
            summary["name"]: int(summary.get("row_count") or 0)
            for summary in model_summaries
        }
        relationships = _infer_relationships(models, row_counts)

        _write_mdl(wren_dir, models, relationships)
        _write_conn(wren_dir)
        if db_path.exists():
            db_path.unlink()
        tmp_db.replace(db_path)

        layer = SemanticLayer(
            dir=str(wren_dir),
            mdl_path=str(wren_dir / "mdl.json"),
            conn_path=str(wren_dir / "conn.json"),
            models=model_summaries,
            relationships=relationships,
        )
        _LAYER_CACHE[session_id] = (fingerprint, layer)
        return layer


def ensure_semantic_layer(session_id: str) -> SemanticLayer | None:
    """build_semantic_layer 的容错包装：任何异常都不阻断分析流程。"""
    try:
        return build_semantic_layer(session_id)
    except Exception:
        return None


def preview_table(session_id: str, table: str, limit: int = 20) -> dict:
    """只读采样预览：直接读 session DuckDB（比走 wren CLI 快一个量级）。

    返回 {columns, rows}；表名经 MDL 白名单校验，防注入。
    """
    limit = max(1, min(int(limit or 20), 200))
    table = str(table or "").strip()
    layer = ensure_semantic_layer(session_id)
    if layer is None:
        raise ValueError("semantic layer unavailable")
    valid_tables = {model["name"] for model in layer.models}
    if table not in valid_tables:
        raise ValueError(f"unknown table: {table}")

    db_path = Path(layer.dir) / f"{CATALOG_NAME}.duckdb"
    if not db_path.exists():
        raise ValueError("duckdb file missing")
    # 只读打开：与执行侧并发读兼容；写锁冲突（极罕见，构建瞬间）时报可读提示
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        result = con.execute(f'SELECT * FROM "{table}" LIMIT {limit}')
        columns = [desc[0] for desc in result.description]
        rows = [
            [None if value is None else str(value) for value in row]
            for row in result.fetchall()
        ]
    finally:
        con.close()
    return {"columns": columns, "rows": rows}


# ---------- NL→SQL 记忆（wren memory 兼容，按用户隔离） ----------
#
# 存储走 wren CLI `memory store`（标准 knowledge/sql/*.md 格式，未来可装
# lancedb extra 升级语义索引）；召回在后端直读 markdown 源文件评分——
# wren grep 后端 token 正则只认 [a-z0-9]，纯中文问题无法命中，故自实现
# 中文感知匹配（字符 bigram + 词元重叠 + 数据源加成）。

MEMORY_BASE_DIRNAME = "_memory"
_MAX_MEMORY_PAIRS = 500
_WORD_TOKEN_RE = re.compile(r"[a-z0-9]+")


def user_memory_project_dir(session_id: str) -> Path | None:
    """用户级 wren memory project 目录（workspace/_memory/<用户名>/）。

    与 wren CLI 完全兼容（wren_project.yml + knowledge/sql/），首次调用
    自动初始化；无法解析归属用户时返回 None（记忆功能停用）。
    """
    from .auth import resolve_user_from_session

    user = resolve_user_from_session(session_id)
    if not user:
        return None
    project = Path(settings.workspace_base_dir) / MEMORY_BASE_DIRNAME / user
    if not (project / "wren_project.yml").exists():
        (project / "knowledge" / "sql").mkdir(parents=True, exist_ok=True)
        (project / "wren_project.yml").write_text(
            "schema_version: 5\nname: deepanalyze-memory\n", encoding="utf-8"
        )
    return project


def _parse_memory_frontmatter(path: Path) -> dict:
    """解析 knowledge/sql/*.md 的 YAML frontmatter（受限子集）。

    兼容两种写入方：
    - 自研 wren_remember（bootstrap 直写）：nl 单引号单行 + sql 块标量 |-
    - wren CLI `memory store`（PyYAML safe_dump）：多行 SQL 为单引号折叠风格
      （续行缩进 2 格，空行代表换行，'' 为转义单引号）
    只按上述形态解析；脏文件返回空 dict（不阻断召回）。
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict = {}
    # 多行值状态：mode（"block" | "quoted"）、pending_key、block_indent（仅块模式）
    mode: str | None = None
    pending_key: str | None = None
    block_indent: int | None = None
    buf: list[str] = []
    ended = False

    def _fold_quoted(parts: list[str]) -> str:
        """YAML 折叠规则：单个换行 → 空格；连续 n 个换行（空行）→ n-1 个换行。"""
        out = ""
        breaks = 0
        for part in parts:
            if not part:
                breaks += 1
                continue
            if not out:
                out = part
            elif breaks:
                out += "\n" * breaks + part
            else:
                out += " " + part
            breaks = 0
        return out

    def _quote_run(text: str) -> int:
        count = 0
        for ch in reversed(text):
            if ch == "'":
                count += 1
            else:
                break
        return count

    def _flush_pending() -> None:
        nonlocal mode, pending_key, block_indent, buf
        if mode == "block" and pending_key:
            data[pending_key] = "\n".join(buf).rstrip("\n")
        elif mode == "quoted" and pending_key:
            data[pending_key] = _fold_quoted(buf).replace("''", "'")
        mode, pending_key, block_indent, buf = None, None, None, []

    for line in lines[1:]:
        if line == "---":  # 与 wren 解析器一致：列 0 的 --- 才是结束符
            _flush_pending()
            ended = True
            break
        if mode == "block":
            if not line.strip():
                buf.append("")
                continue
            indent = len(line) - len(line.lstrip(" "))
            if block_indent is None:
                block_indent = indent
            if indent >= block_indent:
                buf.append(line[block_indent:])
                continue
            _flush_pending()  # 缩进回落 → 块结束，本行按普通键继续
        elif mode == "quoted":
            # 折叠续行：尾引号个数为奇数 → 闭合
            part = line.strip()
            run = _quote_run(part)
            buf.append(part[:-1] if run % 2 == 1 else part)
            if run % 2 == 1:
                _flush_pending()
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            tags = data.setdefault("tags", [])
            if isinstance(tags, list):
                tags.append(stripped[2:].strip())
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value in {"|", "|-", "|+"}:  # 块标量（含 chomping 指示）
                mode, pending_key, block_indent, buf = "block", key, None, []
            elif value.startswith("'"):  # 单引号（可能折叠多行）
                part = value[1:]
                run = _quote_run(part)
                if run % 2 == 1:  # 当行闭合
                    data[key] = _fold_quoted([part[:-1]]).replace("''", "'")
                else:
                    mode, pending_key, buf = "quoted", key, [part]
            elif value:
                data[key] = value
    if not ended:
        _flush_pending()
    if not data.get("nl") or not data.get("sql"):
        return {}
    return data


def _load_memory_pairs(project_dir: Path) -> list[dict]:
    sql_dir = project_dir / "knowledge" / "sql"
    if not sql_dir.is_dir():
        return []
    pairs: list[dict] = []
    for md in sorted(sql_dir.glob("*.md")):
        frontmatter = _parse_memory_frontmatter(md)
        if frontmatter:
            # _path/_mtime 供 embedding 缓存按文件失效（不进入任何输出）
            try:
                frontmatter["_mtime"] = md.stat().st_mtime
            except OSError:
                frontmatter["_mtime"] = 0.0
            frontmatter["_path"] = str(md)
            pairs.append(frontmatter)
        if len(pairs) >= _MAX_MEMORY_PAIRS:
            break
    return pairs


def _word_tokens(text: str) -> set[str]:
    return {
        token
        for token in _WORD_TOKEN_RE.findall(str(text or "").lower())
        if len(token) >= 2
    }


def _char_bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", str(text or "").lower())
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


# ---------- 语义召回（fastembed + bge-small-zh，可选依赖，缺失时词法匹配） ----------

# 实测校准（bge-small-zh-v1.5）：书面同义改写 cos≈0.83+，口语改写 ≈0.67，
# 同域不同问题 ≈0.58-0.64，完全无关 ≈0.31-0.50 —— 门槛取 0.62：召回放宽
# （误召回仅多一行"参考"，漏召回要多轮试错），同域轻度噪声可接受
_SEMANTIC_EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
_SEMANTIC_GATE = 0.62

_EMBEDDER: object | None = None
_EMBEDDER_TRIED = False
_EMBEDDER_LOCK = threading.Lock()
_PAIR_VEC_CACHE: dict[str, tuple[float, object]] = {}
_PAIR_VEC_CACHE_MAX = 2000


def _get_semantic_embedder(wait: bool = True) -> object | None:
    """惰性加载 fastembed 模型（进程内单例）。

    wait=False：正在加载时立即返回 None（本轮回退词法匹配，不阻塞提示词构建）。
    任何失败（未安装/模型下载失败）只降级一次，之后不再重试。
    """
    global _EMBEDDER, _EMBEDDER_TRIED
    if _EMBEDDER_TRIED:
        return _EMBEDDER
    if not _EMBEDDER_LOCK.acquire(blocking=wait):
        return None
    try:
        if _EMBEDDER_TRIED:
            return _EMBEDDER
        from fastembed import TextEmbedding

        _EMBEDDER = TextEmbedding(_SEMANTIC_EMBED_MODEL)
    except Exception:
        _EMBEDDER = None
    finally:
        _EMBEDDER_TRIED = True
        _EMBEDDER_LOCK.release()
    return _EMBEDDER


def prewarm_semantic_embedder() -> None:
    """后端启动时后台预热（首次含模型下载，可能十几秒；不阻塞启动）。"""

    def _warm() -> None:
        try:
            _get_semantic_embedder(wait=True)
        except Exception:
            pass

    threading.Thread(
        target=_warm, daemon=True, name="semantic-embedder-prewarm"
    ).start()


def _embed_one(embedder: object, text: str):
    try:
        vecs = list(embedder.embed([str(text or "")]))  # type: ignore[attr-defined]
        return vecs[0] if vecs else None
    except Exception:
        return None


def _pair_vector(embedder: object, pair: dict):
    """记忆条目 NL 的 embedding（按 md 文件 mtime 缓存）。"""
    import numpy as np

    path = str(pair.get("_path") or "")
    mtime = float(pair.get("_mtime") or 0.0)
    if not path:
        return None
    cached = _PAIR_VEC_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    vec = _embed_one(embedder, str(pair.get("nl") or ""))
    if vec is None:
        return None
    vec = np.asarray(vec, dtype=np.float32)
    if len(_PAIR_VEC_CACHE) >= _PAIR_VEC_CACHE_MAX:
        _PAIR_VEC_CACHE.clear()
    _PAIR_VEC_CACHE[path] = (mtime, vec)
    return vec


def _normalize_memory_datasource(text: str) -> str:
    """数据源标识归一化：文件名 / 表名 / 带重复后缀的文件名统一到可比形式。

    "订单.csv" / "订单" / "订单 (1).csv" → "订单"。datasource 登记的是
    上传文件名，而 current_tables 传的是表名（文件 stem 的清理标识符），
    不归一化两侧永远对不上（数据源加成失效）。
    """
    text = str(text or "").strip()
    if not text:
        return ""
    stem = Path(text).stem
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem).strip()  # 去重复后缀 " (1)"
    return _clean_identifier(stem, stem or "data")


def recall_similar_queries(
    session_id: str,
    question: str,
    *,
    current_tables: list[str] | None = None,
    limit: int = 3,
) -> list[dict]:
    """召回与当前问题相似的历史 NL→SQL 记忆（用户隔离）。

    词法评分：整句包含 > 词元/bigram 重叠率 > 数据源命中。
    语义模式（fastembed 可用时）：cosine 门槛 0.68 先过滤，再与词法分混合排序
    —— 同义改写（"汇总"vs"统计"这类无字面重叠）也能命中。跨 session 表结构
    可能不同，调用方注入提示词时须注明"参考改写、先验证表名列名"。
    """
    project_dir = user_memory_project_dir(session_id)
    if project_dir is None:
        return []
    question = str(question or "").strip()
    if not question:
        return []
    pairs = _load_memory_pairs(project_dir)
    if not pairs:
        return []
    q_lower = question.lower()
    q_words = _word_tokens(question)
    q_bigrams = _char_bigrams(question)
    table_names = {
        _normalize_memory_datasource(t)
        for t in (current_tables or [])
        if str(t or "").strip()
    }
    embedder = None
    q_vec = None
    if settings.memory_semantic_enabled:
        embedder = _get_semantic_embedder(wait=False)
        if embedder is not None:
            q_vec = _embed_one(embedder, question)
    scored: list[tuple[float, dict]] = []
    for pair in pairs:
        nl = str(pair.get("nl") or "")
        nl_lower = nl.lower()
        score = 0.0
        substring_hit = bool(q_lower) and (
            q_lower in nl_lower or nl_lower in q_lower
        )
        if substring_hit:
            score += 10.0
        nl_words = _word_tokens(nl)
        if q_words:
            score += 6.0 * len(q_words & nl_words) / len(q_words)
        nl_bigrams = _char_bigrams(nl)
        if q_bigrams:
            score += 6.0 * len(q_bigrams & nl_bigrams) / len(q_bigrams)
        datasource = str(pair.get("datasource") or "").strip()
        # 同数据源（同上传文件）是强信号，但仅在文本相似度非零时加成：
        # 否则完全无关的问题也会因数据源相同而入选
        normalized_ds = _normalize_memory_datasource(datasource)
        if normalized_ds and normalized_ds in table_names and score > 0:
            score += 8.0
        if q_vec is not None:
            # 语义模式：门槛即 gate（cosine 过滤），词法分作为排序加成
            p_vec = _pair_vector(embedder, pair)  # type: ignore[arg-type]
            if p_vec is None:
                continue
            import numpy as np

            cos = float(
                np.dot(q_vec, p_vec)
                / (np.linalg.norm(q_vec) * np.linalg.norm(p_vec) + 1e-9)
            )
            # 语义未过门槛时，整句包含或强词法命中仍放行（embedding 对字面
            # 改写偶尔保守，词法是兜底信号）
            if cos < _SEMANTIC_GATE and not substring_hit and score < 5.0:
                continue
            score += 10.0 * max(cos, 0.0)
            scored.append((score, pair))
        elif score >= 2.0:  # 词法模式阈值：中文改写 bigram 重叠率通常 0.3-0.6
            scored.append((score, pair))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("nl") or "")))
    return [pair for _, pair in scored[: max(1, limit)]]


# ---------- 记忆管理（前端"查询记忆"面板：浏览 / 删除） ----------

_MEMORY_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.md$")


def list_memory_pairs(session_id: str) -> list[dict]:
    """列出当前用户的全部 NL→SQL 记忆（按文件名排序）。

    session_id 须通过 validate_session_id（归属校验），由路由层保证。
    """
    project_dir = user_memory_project_dir(session_id)
    if project_dir is None:
        return []
    sql_dir = project_dir / "knowledge" / "sql"
    if not sql_dir.is_dir():
        return []
    pairs: list[dict] = []
    for md in sorted(sql_dir.glob("*.md")):
        frontmatter = _parse_memory_frontmatter(md)
        if not frontmatter:
            continue
        pairs.append(
            {
                "file": md.name,
                "nl": str(frontmatter.get("nl") or ""),
                "sql": str(frontmatter.get("sql") or ""),
                "datasource": str(frontmatter.get("datasource") or ""),
            }
        )
    return pairs


def forget_memory_pair(session_id: str, filename: str) -> str:
    """删除一条记忆（按文件名；文件名白名单校验防路径穿越）。"""
    project_dir = user_memory_project_dir(session_id)
    if project_dir is None:
        return "forget failed: user query memory is unavailable"
    filename = str(filename or "").strip()
    if not _MEMORY_FILE_NAME_RE.fullmatch(filename):
        return "forget failed: invalid memory file name"
    path = project_dir / "knowledge" / "sql" / filename
    if not path.is_file():
        return f"forget failed: unknown memory '{filename}'"
    try:
        path.unlink()
    except OSError as exc:
        return f"forget failed: {exc}"
    return f"forgot '{filename}'"


def _render_memory_markdown(nl: str, sql: str, datasource: str) -> tuple[str, str]:
    """渲染一条记忆的 md（与 bootstrap wren_remember 直写的格式一致）。

    返回 (文件名, 内容)；文件名 = slug-hash(nl).md，nl 决定 hash —— 同 NL
    幂等覆盖（与 wren_remember 行为一致）。
    """
    import hashlib as _hashlib

    slug = re.sub(r"[^a-z0-9]+", "-", nl.lower()).strip("-")[:48]
    digest = _hashlib.sha1(nl.encode("utf-8")).hexdigest()[:12]
    front = [
        "---",
        "nl: '" + nl.replace("'", "''") + "'",
        "sql: |-",
    ]
    front += ["  " + ln for ln in sql.splitlines()]
    if datasource:
        front.append("datasource: " + datasource.strip().replace("\n", " "))
    front += ["source: user", "---"]
    return "{}-{}.md".format(slug or "query", digest), "\n".join(front) + "\n"


def add_memory_pair(session_id: str, nl: str, sql: str, datasource: str = "") -> dict:
    """手动添加一条记忆（前端面板）；返回 {status, file} 或 {status}（失败）。"""
    nl = str(nl or "").strip()
    sql = str(sql or "").strip()
    datasource = str(datasource or "").strip()
    if not nl or not sql:
        return {"status": "add failed: need a question and its SQL"}
    project_dir = user_memory_project_dir(session_id)
    if project_dir is None:
        return {"status": "add failed: user query memory is unavailable"}
    sql_dir = project_dir / "knowledge" / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)
    filename, content = _render_memory_markdown(nl, sql, datasource)
    (sql_dir / filename).write_text(content, encoding="utf-8")
    return {"status": "added", "file": filename}


def update_memory_pair(
    session_id: str, filename: str, nl: str, sql: str, datasource: str = ""
) -> dict:
    """编辑一条已有记忆（按文件名；nl 改变则重算 hash 文件名并改名）。"""
    project_dir = user_memory_project_dir(session_id)
    if project_dir is None:
        return {"status": "update failed: user query memory is unavailable"}
    filename = str(filename or "").strip()
    if not _MEMORY_FILE_NAME_RE.fullmatch(filename):
        return {"status": "update failed: invalid memory file name"}
    nl = str(nl or "").strip()
    sql = str(sql or "").strip()
    datasource = str(datasource or "").strip()
    if not nl or not sql:
        return {"status": "update failed: need a question and its SQL"}
    sql_dir = project_dir / "knowledge" / "sql"
    path = sql_dir / filename
    if not path.is_file():
        return {"status": f"update failed: unknown memory '{filename}'"}
    new_filename, content = _render_memory_markdown(nl, sql, datasource)
    try:
        if new_filename != filename:
            path.unlink()
        (sql_dir / new_filename).write_text(content, encoding="utf-8")
    except OSError as exc:
        return {"status": f"update failed: {exc}"}
    return {"status": "updated", "file": new_filename}
