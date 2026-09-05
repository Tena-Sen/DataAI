from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


os.environ.setdefault("MPLBACKEND", "Agg")


def _load_demo_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int_env(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _get_float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _get_port_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        port = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return port


_load_demo_env()


CHINESE_MATPLOTLIB_BOOTSTRAP = """
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False
"""

# WrenAI semantic-layer bridge: wren CLI 位置。
# 语义层按 session 动态构建（上传数据 → DuckDB + MDL，见 services/semantic_builder.py），
# 查询经 wren CLI 定向到 session MDL（显式 --mdl/--connection-file），
# 不依赖任何常驻服务或 wren 工程目录。
WREN_CLI_PATH = os.getenv(
    "DEEPANALYZE_WREN_CLI",
    r"D:\DataAI\WrenAI\.venv\Scripts\wren.exe",
)

# Bootstrap injected into generated analysis code. Plain string with
# __PLACEHOLDER__ tokens (replaced with JSON-quoted values) to avoid
# f-string brace escaping. Session-only: the executor injects
# DEEPANALYZE_WREN_SESSION_DIR pointing at the session semantic layer.
_WREN_BOOTSTRAP_TEMPLATE = '''# --- WrenAI semantic-layer bridge (auto-injected, do not edit) ---
import json as _wren_json
import os as _wren_os
import pathlib as _wren_pl
import time as _wren_time

_WREN_CLI = __WREN_CLI__


def _wren_session_files():
    """Session 语义层（上传数据自动构建）：返回 (mdl_path, conn_path) 或 None。"""
    d = _wren_os.getenv("DEEPANALYZE_WREN_SESSION_DIR")
    if not d:
        return None
    base = _wren_pl.Path(d)
    mdl, conn = base / "mdl.json", base / "conn.json"
    if mdl.exists() and conn.exists():
        return str(mdl), str(conn)
    return None


def _wren_cli(args, timeout=90):
    import subprocess as _sp

    return _sp.run(
        [_WREN_CLI, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


_WREN_SVC = {"sock": None, "down_until": 0.0}


def _wren_service_call(payload, timeout=90):
    """Send a request to the resident wren query service (if configured).

    Returns the response dict, or None when the service is not configured /
    unreachable (callers fall back to the CLI subprocess). A service-side
    query error returns {"ok": false, "error": ...} instead — do NOT fall
    back for those (the CLI would just repeat the error, slower).
    """
    import socket as _wren_socket

    addr = _wren_os.getenv("DEEPANALYZE_WREN_SERVICE")
    if not addr:
        return None
    token = _wren_os.getenv("DEEPANALYZE_WREN_SERVICE_TOKEN")
    if token:
        payload = dict(payload, token=token)
    now = _wren_time.time()
    if now < _WREN_SVC["down_until"]:
        return None
    sock = _WREN_SVC["sock"]
    try:
        if sock is None:
            host, _, port = addr.rpartition(":")
            sock = _wren_socket.create_connection((host, int(port)), timeout=3)
            sock.settimeout(timeout)
            _WREN_SVC["sock"] = sock
        sock.sendall((_wren_json.dumps(payload, ensure_ascii=False) + "\\n").encode("utf-8"))
        buf = b""
        while not buf.endswith(b"\\n"):
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("service closed the connection")
            buf += chunk
        return _wren_json.loads(buf.decode("utf-8"))
    except (OSError, ConnectionError, ValueError):
        try:
            if _WREN_SVC["sock"] is not None:
                _WREN_SVC["sock"].close()
        except OSError:
            pass
        _WREN_SVC["sock"] = None
        _WREN_SVC["down_until"] = now + 30  # 本进程内暂回退 CLI，30s 后重试服务
        return None


def _wren_service_down():
    try:
        if _WREN_SVC["sock"] is not None:
            _WREN_SVC["sock"].close()
    except OSError:
        pass
    _WREN_SVC["sock"] = None


def wren_describe(table, descriptions):
    """Register column meanings into the session data dictionary.

    Call after sampling/inspecting a table (e.g. wren_query with LIMIT, or
    pandas on the raw file): inferred meanings are persisted to
    dictionary.json and automatically injected into later analysis rounds,
    so you never re-guess the same column. Also updates the MDL column
    descriptions used by the engine. Returns a status string (never raises).
    """
    import json as _json

    d = _wren_os.getenv("DEEPANALYZE_WREN_SESSION_DIR")
    if not d:
        return "wren_describe unavailable: no session semantic layer"
    base = _wren_pl.Path(d)
    table = str(table or "").strip()
    clean = {
        str(c).strip(): str(v).strip()
        for c, v in (descriptions or {}).items()
        if str(c).strip() and str(v).strip()
    }
    if not table or not clean:
        return "wren_describe skipped: need table name and {column: meaning}"

    # 1) dictionary.json —— 后续轮次提示词注入用
    dict_path = base / "dictionary.json"
    try:
        dictionary = {}
        if dict_path.exists():
            dictionary = _json.loads(dict_path.read_text(encoding="utf-8")) or {}
        entry = dictionary.get(table) or {}
        entry.update(clean)
        dictionary[table] = entry
        tmp = dict_path.with_suffix(".json.tmp")
        tmp.write_text(
            _json.dumps(dictionary, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(dict_path)
    except Exception as exc:
        return "wren_describe failed (dictionary): {}".format(exc)

    # 2) mdl.json 列 properties.description —— 引擎侧同步
    try:
        mdl_path = base / "mdl.json"
        mdl = _json.loads(mdl_path.read_text(encoding="utf-8"))
        for model in mdl.get("models") or []:
            if model.get("name") != table:
                continue
            for column in model.get("columns") or []:
                meaning = clean.get(column.get("name"))
                if meaning:
                    props = column.setdefault("properties", {})
                    props["description"] = meaning
            break
        tmp = mdl_path.with_suffix(".json.tmp")
        tmp.write_text(
            _json.dumps(mdl, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(mdl_path)
    except Exception:
        pass  # MDL 同步是尽力而为，字典已成功写入
    return "registered {} column meanings for '{}'".format(len(clean), table)


def wren_remember(nl, sql, datasource=None):
    """Register a reusable NL→SQL pair into the user's query memory.

    Call once a wren_query succeeded and the (question, SQL) pair is worth
    reusing later (clear intent, correct tables/columns). Writes a wren
    memory compatible knowledge/sql/<slug>-<hash>.md (valid YAML frontmatter,
    same layout `wren memory` uses) into the user's library; pairs are
    recalled automatically as references in future analyses. Idempotent:
    the same question updates the same file. Returns a status string
    (never raises).
    """
    import hashlib as _wren_hashlib
    import re as _wren_re

    nl = str(nl or "").strip()
    sql = str(sql or "").strip()
    if not nl or not sql:
        return "wren_remember skipped: need a natural-language question and its SQL"
    # 质量门槛：SQL 须引用当前 session 语义层中的至少一张表，防止登记
    # 幻觉表名 / 与本数据无关的查询（子串匹配对 CJK 表名同样有效）
    session_dir = _wren_os.getenv("DEEPANALYZE_WREN_SESSION_DIR")
    if session_dir:
        try:
            mdl = _wren_json.loads(
                (_wren_pl.Path(session_dir) / "mdl.json").read_text(encoding="utf-8")
            )
            names = [
                str(m.get("name"))
                for m in mdl.get("models") or []
                if m.get("name")
            ]
        except Exception:
            names = []
        if names and not any(name in sql for name in names):
            return (
                "wren_remember skipped: SQL references no table from the current "
                "semantic layer; only register queries that actually succeeded "
                "via wren_query"
            )
    project = _wren_os.getenv("WREN_PROJECT_HOME")
    if not project:
        return "wren_remember unavailable: user query memory is not enabled"
    sql_dir = _wren_pl.Path(project) / "knowledge" / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)
    # slug 只含 ascii（中文问题 slug 为空 → 用 hash 兜底）；hash 保证不同问题不冲突
    slug = _wren_re.sub(r"[^a-z0-9]+", "-", nl.lower()).strip("-")[:48]
    digest = _wren_hashlib.sha1(nl.encode("utf-8")).hexdigest()[:12]
    dest = sql_dir / "{}-{}.md".format(slug or "query", digest)
    # nl 单引号风格（'' 转义）；sql 块标量（多行无歧义，wren/自研解析器都好读）
    front = [
        "---",
        "nl: '" + nl.replace("'", "''") + "'",
        "sql: |-",
    ]
    front += ["  " + ln for ln in sql.splitlines()]
    if datasource:
        front.append("datasource: " + str(datasource).strip().replace("\\n", " "))
    front += ["source: user", "---"]
    tmp = dest.parent / (dest.name + ".tmp")
    tmp.write_text("\\n".join(front) + "\\n", encoding="utf-8")
    tmp.replace(dest)
    return "remembered query for future reuse"


def wren_query(sql, limit=None):
    """Query uploaded session data with SQL through the DuckDB semantic layer.

    Table/column names are exactly those listed in the session semantic-layer
    context of the conversation (cleaned identifiers, CJK preserved).
    Returns a pandas DataFrame.
    """
    import pandas as _wren_pd

    sql = str(sql).strip().rstrip(";")
    sess = _wren_session_files()
    if sess is None:
        raise RuntimeError(
            "wren_query unavailable: no uploaded-data semantic layer in this "
            "session. Read the workspace files with pandas instead."
        )
    # Fast path: resident query service (no per-query process startup).
    resp = _wren_service_call(
        {"op": "query", "sql": sql, "mdl": sess[0], "conn": sess[1], "limit": limit}
    )
    if resp is not None:
        if not resp.get("ok"):
            raise RuntimeError(
                "wren_query failed. Check that SQL references uploaded-data table "
                "names exactly as listed in the session semantic layer context:\\n"
                + str(resp.get("error") or "unknown error").strip()[-1500:]
            )
        rows = [
            _wren_json.loads(_line)
            for _line in str(resp.get("rows") or "").splitlines()
            if _line.strip().startswith("{")
        ]
        return _wren_pd.DataFrame(rows)
    cmd = [
        "query",
        "--sql", sql,
        "--mdl", sess[0],
        "--connection-file", sess[1],
        "--output", "json",
        "--quiet",
    ]
    if limit is not None:
        cmd += ["--limit", str(int(limit))]
    proc = _wren_cli(cmd)
    if proc.returncode != 0:
        raise RuntimeError(
            "wren_query failed. Check that SQL references uploaded-data table "
            "names exactly as listed in the session semantic layer context:\\n"
            + (proc.stderr or "unknown error").strip()[-1500:]
        )
    rows = [
        _wren_json.loads(_line)
        for _line in proc.stdout.splitlines()
        if _line.strip().startswith("{")
    ]
    return _wren_pd.DataFrame(rows)


def wren_dry_run(sql):
    """Validate SQL against the session semantic layer without executing it.

    Returns None when the SQL is valid, otherwise the engine's error message.
    """
    sql = str(sql).strip().rstrip(";")
    sess = _wren_session_files()
    if sess is None:
        return "wren_dry_run unavailable: no uploaded-data semantic layer."
    resp = _wren_service_call(
        {"op": "dry_run", "sql": sql, "mdl": sess[0], "conn": sess[1]}, timeout=60
    )
    if resp is not None:
        if resp.get("ok"):
            return None
        return str(resp.get("error") or "unknown error").strip()[-1500:]
    proc = _wren_cli(
        [
            "dry-run",
            "--sql", sql,
            "--mdl", sess[0],
            "--connection-file", sess[1],
        ],
        timeout=60,
    )
    if proc.returncode == 0:
        return None
    return (proc.stderr or proc.stdout or "unknown error").strip()[-1500:]

# --- end WrenAI semantic-layer bridge ---'''


def _build_wren_bootstrap() -> str:
    return _WREN_BOOTSTRAP_TEMPLATE.replace("__WREN_CLI__", json.dumps(WREN_CLI_PATH))


WREN_QUERY_BOOTSTRAP = _build_wren_bootstrap()



# 与 preview_workspace_file 实际支持的格式严格对齐（有按钮就必须能预览）
PREVIEWABLE_EXTENSIONS = {
    # 图片（前端本地渲染）
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".pdf",
    # 文本类
    ".txt",
    ".log",
    ".py",
    ".json",
    ".sql",
    ".yaml",
    ".yml",
    ".md",
    ".markdown",
    # 结构化
    ".csv",
    ".tsv",
    ".xlsx",
    ".docx",  # 纯标准库提取段落/表格文本；.doc 老二进制格式不支持预览
    ".sqlite",
    ".db",
}


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


@dataclass(frozen=True)
class Settings:
    api_base: str = os.getenv("DEEPANALYZE_API_BASE", "http://localhost:8000/v1")
    model_path: str = os.getenv("DEEPANALYZE_MODEL_PATH", "DeepAnalyze-8B")
    workspace_base_dir: str = os.getenv(
        "DEEPANALYZE_WORKSPACE_BASE",
        str(Path(__file__).resolve().parent.parent / "workspace"),
    )
    auth_dir: str = os.getenv(
        "DEEPANALYZE_AUTH_DIR",
        str(Path(__file__).resolve().parent.parent / "auth"),
    )
    http_server_host: str = os.getenv("DEEPANALYZE_FILE_SERVER_HOST", "localhost")
    http_server_port: int = _get_port_env("DEEPANALYZE_FILE_SERVER_PORT", 8100)
    backend_host: str = os.getenv("DEEPANALYZE_BACKEND_HOST", "0.0.0.0")
    backend_port: int = _get_port_env("DEEPANALYZE_BACKEND_PORT", 9000)
    frontend_port: int = _get_port_env("FRONTEND_PORT", 4000)
    execution_mode: str = os.getenv("DEEPANALYZE_EXECUTION_MODE", "docker")
    allow_unsafe_local_execution: bool = _get_bool_env(
        "DEEPANALYZE_ALLOW_UNSAFE_LOCAL_EXECUTION",
        False,
    )
    execution_timeout_sec: int = _get_int_env(
        "DEEPANALYZE_EXECUTION_TIMEOUT_SEC", 120, minimum=1
    )
    docker_image: str = os.getenv(
        "DEEPANALYZE_DOCKER_IMAGE", "deepanalyze-chat-exec:latest"
    )
    docker_auto_build: bool = _get_bool_env(
        "DEEPANALYZE_DOCKER_AUTO_BUILD",
        True,
    )
    docker_container_name: str = os.getenv(
        "DEEPANALYZE_DOCKER_CONTAINER_NAME",
        "deepanalyze-chat-exec",
    )
    docker_session_idle_ttl_sec: int = int(
        os.getenv("DEEPANALYZE_DOCKER_SESSION_IDLE_TTL_SEC", "1800")
    )
    docker_workspace_dir: str = os.getenv("DEEPANALYZE_DOCKER_WORKSPACE_DIR", "/workspace")
    docker_python_bin: str = os.getenv("DEEPANALYZE_DOCKER_PYTHON_BIN", "python")
    docker_network_mode: str = os.getenv("DEEPANALYZE_DOCKER_NETWORK_MODE", "none").strip()
    docker_memory: str = os.getenv("DEEPANALYZE_DOCKER_MEMORY", "1g").strip()
    docker_cpus: float = _get_float_env("DEEPANALYZE_DOCKER_CPUS", 1.0, minimum=0.1)
    docker_pids_limit: int = _get_int_env(
        "DEEPANALYZE_DOCKER_PIDS_LIMIT", 256, minimum=16
    )
    docker_user: str = os.getenv("DEEPANALYZE_DOCKER_USER", "1000:1000").strip()
    docker_read_only: bool = _get_bool_env("DEEPANALYZE_DOCKER_READ_ONLY", True)
    docker_tmpfs_size: str = os.getenv(
        "DEEPANALYZE_DOCKER_TMPFS_SIZE", "256m"
    ).strip()
    docker_stop_on_shutdown: bool = _get_bool_env(
        "DEEPANALYZE_DOCKER_STOP_ON_SHUTDOWN",
        True,
    )
    pdf_cjk_mainfont: str = os.getenv("DEEPANALYZE_PDF_CJK_MAINFONT", "").strip()
    pdf_auto_download_pandoc: bool = _get_bool_env(
        "DEEPANALYZE_PDF_AUTO_DOWNLOAD_PANDOC",
        True,
    )
    pdf_pandoc_cache_dir: str = os.getenv(
        "DEEPANALYZE_PDF_PANDOC_CACHE_DIR",
        "",
    ).strip()
    upload_max_file_bytes: int = _get_int_env(
        "DEEPANALYZE_UPLOAD_MAX_FILE_BYTES", 100 * 1024 * 1024, minimum=1
    )
    workspace_max_bytes: int = _get_int_env(
        "DEEPANALYZE_WORKSPACE_MAX_BYTES", 1024 * 1024 * 1024, minimum=1
    )
    workspace_max_files: int = _get_int_env(
        "DEEPANALYZE_WORKSPACE_MAX_FILES", 500, minimum=1
    )
    upload_chunk_bytes: int = _get_int_env(
        "DEEPANALYZE_UPLOAD_CHUNK_BYTES", 1024 * 1024, minimum=64 * 1024
    )
    chat_max_rounds: int = _get_int_env("DEEPANALYZE_CHAT_MAX_ROUNDS", 12, minimum=1)
    chat_max_duration_sec: int = _get_int_env(
        "DEEPANALYZE_CHAT_MAX_DURATION_SEC", 900, minimum=1
    )
    chat_max_response_chars: int = _get_int_env(
        "DEEPANALYZE_CHAT_MAX_RESPONSE_CHARS", 1_000_000, minimum=1024
    )
    # 默认 180s：思考型模型（如 MiniMax-M3）长思考期间可能长时间不产生字节
    model_stream_read_timeout_sec: int = _get_int_env(
        "DEEPANALYZE_MODEL_STREAM_READ_TIMEOUT_SEC", 180, minimum=5
    )
    execution_output_max_chars: int = _get_int_env(
        "DEEPANALYZE_EXECUTION_OUTPUT_MAX_CHARS", 32768, minimum=1024
    )
    enable_external_proxy: bool = _get_bool_env(
        "DEEPANALYZE_ENABLE_EXTERNAL_PROXY",
        False,
    )
    # wren 查询常驻服务（省去每次查询 ~1s 的 CLI 进程启动开销）
    wren_cli_path: str = WREN_CLI_PATH
    wren_service_enabled: bool = _get_bool_env(
        "DEEPANALYZE_WREN_SERVICE",
        True,
    )
    wren_service_port: int = _get_port_env("DEEPANALYZE_WREN_SERVICE_PORT", 9471)
    # NL→SQL 记忆语义召回（fastembed，不可用时回退词元/bigram 匹配）
    memory_semantic_enabled: bool = _get_bool_env(
        "DEEPANALYZE_MEMORY_SEMANTIC",
        True,
    )

    @property
    def file_server_base(self) -> str:
        return f"http://{self.http_server_host}:{self.http_server_port}"

    @property
    def use_docker_execution(self) -> bool:
        return self.execution_mode.strip().lower() == "docker"


settings = Settings()
