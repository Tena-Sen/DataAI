"""Wren 查询常驻服务 driver（独立脚本，由 WrenAI venv 的 python 运行）。

复刻 `wren query / dry-run` CLI 的每请求流程（读 MDL → base64 → WrenEngine →
执行 → 关闭），但进程常驻：省去每次查询 ~1s 的解释器启动 + 包导入开销。

协议：TCP 127.0.0.1:PORT，换行分隔 JSON（NDJSON），一连接多请求：
- 请求 {"op": "ping"}
       {"op": "query"|"dry_run", "sql": str, "mdl": path, "conn": path, "limit": int?,
        "token": str}
- 响应 {"ok": true, "pong": true}
       {"ok": true, "rows": "<ndjson 字符串，与 CLI --output json 逐行一致>"}
       {"ok": true, "dry": true}
       {"ok": false, "error": "<原因>"}

鉴权：--token-file 指定启动时生成的随机 token 文件路径；请求 token 不匹配
直接拒绝（本机其他进程无法借服务查任意 session 数据）。

用法：python wren_query_service_driver.py --port 9471 --token-file <path>
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import socket
import socketserver
import sys
import threading
from contextlib import suppress
from pathlib import Path


def _log(message: str) -> None:
    print(f"[wren-service] {message}", flush=True)


# ---- wren 引擎封装（与 cli.py 的 query/dry-run 路径保持一致） ----

_WREN_HOME = Path(
    __import__("os").environ.get("WREN_HOME", str(Path.home() / ".wren"))
).expanduser()

_engine_lock = threading.Lock()  # 引擎构建/执行串行化：避免并发 DuckDB 文件锁
_auth_token: str | None = None  # 启动时生成；None 表示本实例未启用鉴权


def _build_engine(mdl_path: str, conn_path: str):
    from wren.config import load_config
    from wren.engine import WrenEngine
    from wren.model.data_source import DataSource

    mdl_file = Path(mdl_path)
    conn_file = Path(conn_path)
    if not mdl_file.exists() or not conn_file.exists():
        raise FileNotFoundError("mdl.json / conn.json not found")
    manifest_str = base64.b64encode(mdl_file.read_bytes()).decode()
    conn = json.loads(conn_file.read_text(encoding="utf-8"))
    try:
        config = load_config(_WREN_HOME)
    except Exception:
        from wren.config import WrenConfig

        config = WrenConfig()
    return WrenEngine(
        manifest_str=manifest_str,
        data_source=DataSource(str(conn.get("datasource") or "duckdb").lower()),
        connection_info=conn,
        config=config,
    )


def _handle_request(payload: dict) -> dict:
    if _auth_token is not None and payload.get("token") != _auth_token:
        return {"ok": False, "error": "unauthorized"}
    op = str(payload.get("op") or "")
    if op == "ping":
        return {"ok": True, "pong": True}
    if op not in {"query", "dry_run"}:
        return {"ok": False, "error": f"unknown op: {op!r}"}
    sql = str(payload.get("sql") or "").strip()
    mdl = str(payload.get("mdl") or "")
    conn = str(payload.get("conn") or "")
    if not sql or not mdl or not conn:
        return {"ok": False, "error": "need sql, mdl and conn"}
    limit = payload.get("limit")
    try:
        with _engine_lock:
            with _build_engine(mdl, conn) as engine:
                if op == "dry_run":
                    engine.dry_run(sql)
                    return {"ok": True, "dry": True}
                table = engine.query(sql, limit=int(limit) if limit else None)
        # 与 CLI --output json 完全一致的行格式（pandas to_json records/lines）
        import pandas as pd

        rows = pd.DataFrame(table.to_pydict()).to_json(orient="records", lines=True)
        return {"ok": True, "rows": rows or ""}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


class _Handler(socketserver.StreamRequestHandler):
    """一连接多请求：逐行读请求，逐行写响应。"""

    def handle(self) -> None:
        while True:
            try:
                line = self.rfile.readline()
            except OSError:
                return
            if not line:
                return  # 对端关闭
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except ValueError:
                response = {"ok": False, "error": "invalid JSON request"}
            else:
                if not isinstance(payload, dict):
                    response = {"ok": False, "error": "request must be an object"}
                else:
                    response = _handle_request(payload)
            try:
                self.wfile.write(
                    (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
                )
                self.wfile.flush()
            except OSError:
                return


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9471)
    parser.add_argument(
        "--token-file",
        help="生成随机 token 写入此文件（服务端鉴权；调用方须在请求中携带同值 token）",
    )
    args = parser.parse_args()

    if args.token_file:
        token_path = Path(args.token_file)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(32)
        tmp = token_path.with_suffix(".tmp")
        tmp.write_text(token, encoding="utf-8")
        tmp.replace(token_path)
        globals()["_auth_token"] = token
        _log(f"auth enabled (token at {token_path})")

    # 启动即预热导入：首次真实请求不再付导入成本
    try:
        import pandas as pd  # noqa: F401
        from wren.engine import WrenEngine  # noqa: F401
    except Exception as exc:
        _log(f"import failed: {exc}")
        return 1

    server = _ThreadingTCPServer(("127.0.0.1", args.port), _Handler)
    _log(f"listening on 127.0.0.1:{args.port}")
    try:
        server.serve_forever(poll_interval=1.0)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        # 注意：不删 token 文件。旧实例退出时删文件会连带删掉新实例刚写入的
        # token（重启竞态 → 后端永久误判死亡 → 重启循环）。token 文件的清理由
        # 管理器（后端）在整体停止时负责。
    return 0


if __name__ == "__main__":
    sys.exit(main())
