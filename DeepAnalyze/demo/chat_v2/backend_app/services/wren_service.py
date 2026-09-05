"""Wren 查询常驻服务管理器（后端侧）。

后端启动时拉起 driver 子进程（WrenAI venv python），周期 ping 保活，崩溃自动
重启；关闭时终止。执行子进程通过环境变量 DEEPANALYZE_WREN_SERVICE 得知服务
地址，bootstrap 的 wren_query/wren_dry_run 优先走服务，不可达时回退 CLI。

服务不可用不影响功能：所有调用方都有 CLI 子进程回退路径。
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from ..settings import settings

logger = logging.getLogger(__name__)

_DRIVER_PATH = Path(__file__).resolve().parent / "wren_query_service_driver.py"
_PING_INTERVAL_SEC = 30
_STARTUP_TIMEOUT_SEC = 45  # driver 冷启动需导入 pandas+wren（磁盘缓存冷时 >20s）

_state_lock = threading.Lock()
_process: subprocess.Popen | None = None
_external_service = False  # 端口已被外部服务占用（复用，不纳管生命周期）
_monitor_thread: threading.Thread | None = None
_stopping = False
_auth_token: str | None = None  # 本管理器拉起实例的请求 token（外部实例为 None）


def _token_file_path() -> Path:
    """token 文件位置：随 workspace 放置，便于按用户权限隔离访问。"""
    base = Path(settings.workspace_base_dir).resolve().parent
    return base / "logs" / "wren_service.token"


def _wren_python() -> str | None:
    """WrenAI venv 的 python（与 wren.exe 同目录）。"""
    candidate = Path(settings.wren_cli_path).with_name("python.exe")
    if candidate.exists():
        return str(candidate)
    return None


def _load_token_from_file() -> str | None:
    """从 token 文件读取（外部接管检测用：进程刚启动时内存里还没有 token）。"""
    global _auth_token
    if _auth_token is None:
        try:
            _auth_token = _token_file_path().read_text(encoding="utf-8").strip() or None
        except OSError:
            _auth_token = None
    return _auth_token


def _ping(port: int, timeout: float = 2.0) -> bool:
    import json

    payload: dict = {"op": "ping"}
    token = _load_token_from_file()
    if token:
        payload["token"] = token
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    return False
                buf += chunk
            resp = json.loads(buf.decode("utf-8"))
            return bool(resp.get("ok") and resp.get("pong"))
    except (OSError, ValueError):
        return False


def _spawn(port: int) -> bool:
    global _process, _auth_token
    python = _wren_python()
    if python is None:
        logger.warning("wren service disabled: python not found next to wren CLI")
        return False
    _auth_token = None  # 每次拉起都生成新 token（driver 启动时写入）
    log_dir = Path(settings.workspace_base_dir).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "wren_service.log"
    token_file = _token_file_path()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    log_file = open(log_path, "ab")
    try:
        _process = subprocess.Popen(
            [
                python,
                str(_DRIVER_PATH),
                "--port",
                str(port),
                "--token-file",
                str(token_file),
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    finally:
        # Popen 已继承句柄；close 只关掉父进程这一端
        log_file.close()
    deadline = time.monotonic() + _STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if _process.poll() is not None:
            logger.warning("wren service exited during startup (code %s)", _process.returncode)
            return False
        # 每轮重读 token 文件（driver 启动时写入新值；重置残留的旧 token）
        try:
            _auth_token = token_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            _auth_token = None
        if _auth_token and _ping(port):
            logger.info("wren query service started on 127.0.0.1:%s (pid %s)", port, _process.pid)
            return True
        time.sleep(0.5)
    logger.warning("wren service startup timed out after %ss", _STARTUP_TIMEOUT_SEC)
    return False


def _monitor_loop(port: int) -> None:
    """周期保活：崩溃/被杀后自动重启。"""
    global _process
    consecutive_failures = 0
    while not _stopping:
        time.sleep(_PING_INTERVAL_SEC)
        if _stopping:
            return
        with _state_lock:
            if _external_service:
                return  # 外部服务不纳管
        if _ping(port):
            consecutive_failures = 0
            continue
        consecutive_failures += 1
        if consecutive_failures < 2:
            continue  # 单次失败可能是瞬时端口占用，再等一轮
        logger.warning("wren service unresponsive, restarting (failures=%s)", consecutive_failures)
        with _state_lock:
            _terminate_process()
            _spawn(port)
        consecutive_failures = 0


def _terminate_process() -> None:
    global _process
    proc = _process
    _process = None
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def start_wren_service() -> None:
    """后端启动入口：启动常驻查询服务 + 保活线程（已禁用/已占用则跳过）。"""
    global _external_service, _monitor_thread, _stopping
    if not settings.wren_service_enabled:
        return
    if settings.use_docker_execution:
        # docker 模式：容器 network=none 访问不到宿主机服务，执行侧仍走 CLI
        return
    port = settings.wren_service_port
    with _state_lock:
        if _ping(port):
            _external_service = True
            logger.info("wren query service already running on 127.0.0.1:%s (external)", port)
            return
        if not _spawn(port):
            # 冷启动超时不代表 driver 死了（可能稍后完成监听）：monitor 线程照常
            # 启动，由它 ping 探活 / 崩溃重启，服务恢复后自动重新纳管
            logger.warning("wren service slow to start; monitor will keep probing")
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _stopping = False
            _monitor_thread = threading.Thread(
                target=_monitor_loop, args=(port,), daemon=True, name="wren-service-monitor"
            )
            _monitor_thread.start()


def stop_wren_service() -> None:
    """后端关闭入口（外部服务不动）。"""
    global _stopping
    _stopping = True
    with _state_lock:
        if not _external_service:
            _terminate_process()
            # driver 不再自删 token 文件（防重启竞态），由这里统一清理
            try:
                _token_file_path().unlink(missing_ok=True)
            except OSError:
                pass


def service_address_if_running() -> tuple[str, str] | None:
    """服务健康时返回 ("127.0.0.1:<port>", token)，否则 None。

    执行子进程据此注入 env（地址 + 鉴权 token）；ping 失败不触发重启
    （由保活线程负责），仅如实上报当前状态。token 为空字符串表示该
    实例未启用鉴权（外部实例 / 兼容旧 driver）。
    """
    if not settings.wren_service_enabled or settings.use_docker_execution:
        return None
    port = settings.wren_service_port
    if _ping(port):
        return f"127.0.0.1:{port}", _auth_token or ""
    return None
