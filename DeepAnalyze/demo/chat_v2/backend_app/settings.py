from __future__ import annotations

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

# WrenAI semantic-layer bridge: wren CLI location and project directory used by
# the auto-injected wren_query() helper in generated analysis code.
WREN_CLI_PATH = os.getenv(
    "DEEPANALYZE_WREN_CLI",
    r"D:\DataAI\WrenAI\.venv\Scripts\wren.exe",
)
WREN_PROJECT_DIR = os.getenv(
    "DEEPANALYZE_WREN_PROJECT",
    r"D:\DataAI\wren-jaffle",
)

WREN_QUERY_BOOTSTRAP = f'''# --- WrenAI semantic-layer bridge (auto-injected, do not edit) ---
def wren_query(sql, limit=None):
    """Run governed SQL through the WrenAI semantic layer.

    SQL must reference semantic model/view/cube names (see system prompt),
    not raw database tables. Returns a pandas DataFrame.

    Cube queries (`FROM <cube_name>`) are auto-routed to the structured
    cube engine: known measure columns become --measures, other selected
    columns become --dimensions.
    """
    import json as _wren_json
    import re as _wren_re
    import subprocess as _wren_sp

    import pandas as _wren_pd

    def _run(args):
        return _wren_sp.run(
            [r"{WREN_CLI_PATH}", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=r"{WREN_PROJECT_DIR}",
            timeout=90,
        )

    def _rows_from(stdout):
        return [
            _wren_json.loads(_line)
            for _line in stdout.splitlines()
            if _line.strip().startswith("{{")
        ]

    sql = str(sql).strip().rstrip(";")
    cube_match = _wren_re.search(
        r"FROM\s+([A-Za-z_][\w]*)\s*$", sql, _wren_re.IGNORECASE
    )
    if cube_match:
        cube = cube_match.group(1)
        select_part = sql[: cube_match.start()]
        cols_match = _wren_re.search(
            r"SELECT\s+(.*?)\s*$", select_part, _wren_re.IGNORECASE | _wren_re.DOTALL
        )
        cols = []
        if cols_match:
            cols = [
                c.strip()
                for c in cols_match.group(1).split(",")
                if c.strip() and c.strip() != "*"
            ]
        known_measures = {{"total_revenue", "order_count"}}
        measures = [c for c in cols if c in known_measures]
        dimensions = [c for c in cols if c not in known_measures]
        args = ["cube", "query", "--cube", cube]
        if measures:
            args += ["--measures", ",".join(measures)]
        if dimensions:
            args += ["--dimensions", ",".join(dimensions)]
        if limit is not None:
            args += ["--limit", str(int(limit))]
        args += ["--output", "json"]
        _proc = _run(args)
        if _proc.returncode != 0:
            _err = (_proc.stderr or "unknown error").strip()[-1500:]
            raise RuntimeError(
                "wren_query failed (cube {{}}):\\n{{}}".format(cube, _err)
            )
        return _wren_pd.DataFrame(_rows_from(_proc.stdout))

    _cmd = ["query", "--sql", sql, "--output", "json"]
    if limit is not None:
        _cmd += ["--limit", str(int(limit))]
    _proc = _run([*_cmd, "--quiet"])
    if _proc.returncode != 0:
        _err = (_proc.stderr or "unknown error").strip()[-1500:]
        raise RuntimeError(
            "wren_query failed. Check that SQL uses semantic object names "
            "(orders, customers, customer_orders); cubes are queried via "
            "FROM order_metrics with measure columns:\\n" + _err
        )
    return _wren_pd.DataFrame(_rows_from(_proc.stdout))


# --- end WrenAI semantic-layer bridge ---'''



PREVIEWABLE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".pdf",
    ".txt",
    ".doc",
    ".docx",
    ".csv",
    ".xlsx",
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
    model_stream_read_timeout_sec: int = _get_int_env(
        "DEEPANALYZE_MODEL_STREAM_READ_TIMEOUT_SEC", 60, minimum=5
    )
    execution_output_max_chars: int = _get_int_env(
        "DEEPANALYZE_EXECUTION_OUTPUT_MAX_CHARS", 32768, minimum=1024
    )
    enable_external_proxy: bool = _get_bool_env(
        "DEEPANALYZE_ENABLE_EXTERNAL_PROXY",
        False,
    )

    @property
    def file_server_base(self) -> str:
        return f"http://{self.http_server_host}:{self.http_server_port}"

    @property
    def use_docker_execution(self) -> bool:
        return self.execution_mode.strip().lower() == "docker"


settings = Settings()
