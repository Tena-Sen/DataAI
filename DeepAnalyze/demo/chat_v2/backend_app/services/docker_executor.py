from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from ..settings import settings
from .workspace import resolve_workspace_root, validate_session_id


MANAGED_LABEL_KEY = "deepanalyze.managed"
SESSION_LABEL_KEY = "deepanalyze.session"
APP_LABEL_KEY = "deepanalyze.app"
APP_LABEL_VALUE = "chat-v2"
OWNER_LABEL_KEY = "deepanalyze.owner"
DOCKER_BUILD_TIMEOUT_SEC = 1800

logger = logging.getLogger(__name__)


@dataclass
class SessionContainerState:
    session_id: str
    container_name: str
    created_by_app: bool
    started_by_app: bool
    last_used_at: float


_DOCKER_LOCK = threading.Lock()
_SESSION_CONTAINERS: dict[str, SessionContainerState] = {}


def _run_docker_command(
    args: list[str],
    *,
    check: bool = True,
    timeout: int | None = 60,
) -> subprocess.CompletedProcess[str]:
    # A default timeout guards every call: a wedged Docker daemon would otherwise
    # hang the caller (and, via _DOCKER_LOCK, every other session) indefinitely.
    try:
        return subprocess.run(
            ["docker", *args],
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Docker command timed out after {timeout}s: docker {' '.join(args[:2])} ..."
        ) from exc


def _keepalive_command() -> list[str]:
    return ["sh", "-c", "while true; do sleep 3600; done"]


def _sanitize_session_id(session_id: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", (session_id or "default").strip())
    normalized = normalized.strip(".-") or "default"
    return normalized[:48]


def _deployment_owner_id() -> str:
    workspace_base = str(Path(settings.workspace_base_dir).resolve()).replace("\\", "/")
    return hashlib.sha256(workspace_base.casefold().encode("utf-8")).hexdigest()[:16]


def _legacy_container_name_for_session(session_id: str) -> str:
    validated_session_id = validate_session_id(session_id)
    prefix = settings.docker_container_name.strip() or "deepanalyze-chat-exec"
    digest = hashlib.sha256(validated_session_id.encode("utf-8")).hexdigest()[:12]
    suffix = f"{_sanitize_session_id(validated_session_id)[:32]}-{digest}"
    return f"{prefix}-{suffix}"[:120]


def _v0_container_name_for_session(session_id: str) -> str:
    validated_session_id = validate_session_id(session_id)
    prefix = settings.docker_container_name.strip() or "deepanalyze-chat-exec"
    return f"{prefix}-{_sanitize_session_id(validated_session_id)}"[:120]


def _container_name_for_session(session_id: str) -> str:
    validated_session_id = validate_session_id(session_id)
    prefix = settings.docker_container_name.strip() or "deepanalyze-chat-exec"
    identity = f"{_deployment_owner_id()}:{validated_session_id}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    suffix = f"{_sanitize_session_id(validated_session_id)[:32]}-{digest}"
    return f"{prefix}-{suffix}"[:120]


def _container_exists(container_name: str) -> bool:
    completed = _run_docker_command(
        ["ps", "-a", "--filter", f"name=^{container_name}$", "--format", "{{.Names}}"],
        check=False,
    )
    return container_name in (completed.stdout or "").splitlines()


def _container_exists_checked(container_name: str) -> bool:
    completed = _run_docker_command(
        ["ps", "-a", "--filter", f"name=^{container_name}$", "--format", "{{.Names}}"],
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "unknown Docker error").strip()
        raise RuntimeError(f"Failed to query container {container_name}: {details}")
    return container_name in (completed.stdout or "").splitlines()


def _container_is_running(container_name: str) -> bool:
    completed = _run_docker_command(
        ["inspect", "-f", "{{.State.Running}}", container_name],
        check=False,
    )
    return (completed.returncode == 0) and (completed.stdout or "").strip().lower() == "true"


def _image_exists(image_name: str) -> bool:
    completed = _run_docker_command(
        ["image", "inspect", image_name],
        check=False,
        timeout=20,
    )
    return completed.returncode == 0


def _ensure_docker_daemon_available() -> None:
    completed = _run_docker_command(
        ["info", "--format", "{{.ServerVersion}}"],
        check=False,
        timeout=20,
    )
    if completed.returncode == 0:
        return
    details = (completed.stderr or completed.stdout or "unknown Docker error").strip()
    raise RuntimeError(
        "Docker daemon is unavailable. Start Docker Desktop (or the Docker daemon) "
        f"and retry. Details: {details}"
    )


def _ensure_docker_image_available() -> None:
    if _image_exists(settings.docker_image):
        return

    dockerfile = Path(__file__).resolve().parents[2] / "Dockerfile.exec"
    if not settings.docker_auto_build:
        raise RuntimeError(
            f"Docker image {settings.docker_image!r} was not found. "
            f"Build it from {dockerfile.parent} or enable "
            "DEEPANALYZE_DOCKER_AUTO_BUILD."
        )
    if not dockerfile.is_file():
        raise RuntimeError(
            f"Docker image {settings.docker_image!r} was not found and the build file "
            f"does not exist: {dockerfile}"
        )

    logger.info(
        "Docker image %s was not found; building it from %s",
        settings.docker_image,
        dockerfile,
    )
    completed = _run_docker_command(
        [
            "build",
            "-t",
            settings.docker_image,
            "-f",
            str(dockerfile),
            str(dockerfile.parent),
        ],
        check=False,
        timeout=DOCKER_BUILD_TIMEOUT_SEC,
    )
    if completed.returncode == 0:
        logger.info("Docker image %s built successfully", settings.docker_image)
        return
    details = (completed.stderr or completed.stdout or "unknown Docker error").strip()
    raise RuntimeError(
        f"Failed to build Docker image {settings.docker_image!r} from {dockerfile}: "
        f"{details}"
    )


def _inspect_container(container_name: str) -> dict | None:
    completed = _run_docker_command(
        ["inspect", container_name],
        check=False,
        timeout=20,
    )
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout or "[]")[0]
    except (IndexError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _payload_matches_session(
    payload: dict,
    session_id: str,
    session_workspace: Path,
) -> bool:
    labels = payload.get("Config", {}).get("Labels", {}) or {}
    mounts = payload.get("Mounts", []) or []
    if labels.get(MANAGED_LABEL_KEY) != "true" or labels.get(SESSION_LABEL_KEY) != session_id:
        return False
    expected_source = session_workspace.resolve()
    return any(
        mount.get("Destination") == settings.docker_workspace_dir
        and Path(str(mount.get("Source") or "")).resolve() == expected_source
        for mount in mounts
    )


def _payload_mounts_workspace(payload: dict, workspace: Path) -> bool:
    expected_source = workspace.resolve()
    return any(
        mount.get("Destination") == settings.docker_workspace_dir
        and Path(str(mount.get("Source") or "")).resolve() == expected_source
        for mount in (payload.get("Mounts", []) or [])
    )


def _container_matches_session(
    container_name: str,
    session_id: str,
    session_workspace: Path,
) -> bool:
    payload = _inspect_container(container_name)
    return bool(payload and _payload_matches_session(payload, session_id, session_workspace))


def _container_matches_current_session(
    container_name: str,
    session_id: str,
    session_workspace: Path,
) -> bool:
    payload = _inspect_container(container_name)
    return bool(
        payload
        and _payload_matches_session(payload, session_id, session_workspace)
        and _container_belongs_to_current_app(container_name, payload)
    )


def _container_identity(payload: dict) -> tuple[str, str]:
    labels = payload.get("Config", {}).get("Labels", {}) or {}
    return str(labels.get(APP_LABEL_KEY) or ""), str(labels.get(OWNER_LABEL_KEY) or "")


def _container_belongs_to_current_app(container_name: str, payload: dict) -> bool:
    labels = payload.get("Config", {}).get("Labels", {}) or {}
    if labels.get(MANAGED_LABEL_KEY) != "true":
        return False
    session_id = str(labels.get(SESSION_LABEL_KEY) or "")
    try:
        validated_session_id = validate_session_id(session_id)
    except Exception:
        return False

    workspace_base = Path(settings.workspace_base_dir).resolve()
    session_workspace = workspace_base / validated_session_id
    app_label, owner_label = _container_identity(payload)
    if app_label or owner_label:
        return (
            app_label == APP_LABEL_VALUE
            and owner_label == _deployment_owner_id()
            and container_name == _container_name_for_session(validated_session_id)
            and _payload_matches_session(payload, validated_session_id, session_workspace)
        )

    image_name = str(payload.get("Config", {}).get("Image") or "")
    if image_name != settings.docker_image:
        return False
    if container_name == _legacy_container_name_for_session(validated_session_id):
        return _payload_matches_session(payload, validated_session_id, session_workspace)
    return (
        container_name == _v0_container_name_for_session(validated_session_id)
        and _payload_mounts_workspace(payload, workspace_base)
    )


def _container_started_timestamp(payload: dict, fallback: float) -> float:
    raw_value = str(
        payload.get("State", {}).get("StartedAt") or payload.get("Created") or ""
    ).strip()
    if not raw_value:
        return fallback
    normalized = raw_value.replace("Z", "+00:00")
    normalized = re.sub(r"(\.\d{6})\d+(?=[+-])", r"\1", normalized)
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return fallback


def _touch_container(session_id: str, container_name: str, *, created_by_app: bool, started_by_app: bool) -> None:
    state = _SESSION_CONTAINERS.get(session_id)
    now = time.time()
    if state is None:
        _SESSION_CONTAINERS[session_id] = SessionContainerState(
            session_id=session_id,
            container_name=container_name,
            created_by_app=created_by_app,
            started_by_app=started_by_app,
            last_used_at=now,
        )
        return
    state.last_used_at = now
    state.created_by_app = state.created_by_app or created_by_app
    state.started_by_app = state.started_by_app or started_by_app


def _remove_container(container_name: str, *, remove: bool) -> None:
    action = ["rm", "-f", container_name] if remove else ["stop", container_name]
    completed = _run_docker_command(action, check=False, timeout=20)
    if completed.returncode == 0:
        return
    details = (completed.stderr or completed.stdout or "unknown Docker error").strip()
    if _container_exists_checked(container_name):
        raise RuntimeError(f"Failed to release container {container_name}: {details}")


def _discover_managed_containers(now: float) -> None:
    completed = _run_docker_command(
        [
            "ps",
            "-a",
            "--filter",
            f"label={MANAGED_LABEL_KEY}=true",
            "--format",
            "{{.Names}}",
        ],
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "unknown Docker error").strip()
        raise RuntimeError(f"Failed to discover managed containers: {details}")

    for container_name in (completed.stdout or "").splitlines():
        container_name = container_name.strip()
        if not container_name:
            continue
        payload = _inspect_container(container_name)
        if not payload or not _container_belongs_to_current_app(container_name, payload):
            continue
        labels = payload.get("Config", {}).get("Labels", {}) or {}
        session_id = validate_session_id(str(labels.get(SESSION_LABEL_KEY) or ""))
        _SESSION_CONTAINERS.setdefault(
            session_id,
            SessionContainerState(
                session_id=session_id,
                container_name=container_name,
                created_by_app=True,
                started_by_app=bool(payload.get("State", {}).get("Running")),
                last_used_at=_container_started_timestamp(payload, now),
            ),
        )


def _cleanup_idle_session_containers(now: float | None = None) -> None:
    if not settings.use_docker_execution:
        return

    ttl = max(0, settings.docker_session_idle_ttl_sec)
    if ttl <= 0:
        return

    now = now or time.time()
    expired_sessions = [
        session_id
        for session_id, state in _SESSION_CONTAINERS.items()
        if now - state.last_used_at >= ttl
    ]
    for session_id in expired_sessions:
        state = _SESSION_CONTAINERS.get(session_id)
        if state is None:
            continue
        try:
            _remove_container(state.container_name, remove=state.created_by_app)
        except RuntimeError as exc:
            logger.warning(
                "idle container cleanup failed session_id=%s container=%s error=%s",
                session_id,
                state.container_name,
                exc,
            )
            continue
        if _SESSION_CONTAINERS.get(session_id) is state:
            _SESSION_CONTAINERS.pop(session_id, None)


def cleanup_idle_containers(now: float | None = None) -> None:
    """Public entry point for the periodic idle-container reaper."""
    if not settings.use_docker_execution:
        return
    with _DOCKER_LOCK:
        effective_now = now or time.time()
        _discover_managed_containers(effective_now)
        _cleanup_idle_session_containers(effective_now)


def release_session_container(session_id: str) -> bool:
    """Release current and legacy execution containers for one session."""
    if not settings.use_docker_execution:
        return False

    validated_session_id = validate_session_id(session_id)
    candidate_names = [
        _container_name_for_session(validated_session_id),
        _legacy_container_name_for_session(validated_session_id),
        _v0_container_name_for_session(validated_session_id),
    ]
    released = False
    with _DOCKER_LOCK:
        for container_name in dict.fromkeys(candidate_names):
            if not _container_exists_checked(container_name):
                continue
            payload = _inspect_container(container_name)
            if not payload or not _container_belongs_to_current_app(container_name, payload):
                raise RuntimeError(
                    f"Execution container {container_name} failed ownership validation"
                )
            _remove_container(container_name, remove=True)
            released = True
        if released:
            _SESSION_CONTAINERS.pop(validated_session_id, None)
            logger.info("session container released session_id=%s", validated_session_id)
    return released


def ensure_execution_backend_ready(session_id: str | None = None) -> None:
    if not settings.use_docker_execution or not session_id:
        return

    validated_session_id = validate_session_id(session_id)
    session_workspace = resolve_workspace_root(validated_session_id)
    container_name = _container_name_for_session(session_id)

    with _DOCKER_LOCK:
        _cleanup_idle_session_containers()

        if _container_is_running(container_name):
            if not _container_matches_current_session(
                container_name, validated_session_id, session_workspace
            ):
                raise RuntimeError("Existing execution container failed isolation validation")
            _touch_container(
                validated_session_id,
                container_name,
                created_by_app=True,
                started_by_app=False,
            )
            return

        if _container_exists(container_name):
            if not _container_matches_current_session(
                container_name, validated_session_id, session_workspace
            ):
                raise RuntimeError("Existing execution container failed isolation validation")
            _run_docker_command(["start", container_name])
            _touch_container(
                validated_session_id,
                container_name,
                created_by_app=True,
                started_by_app=True,
            )
            return

        _ensure_docker_image_available()

        docker_args = [
                "run",
                "-d",
                "--name",
                container_name,
                "--label",
                f"{MANAGED_LABEL_KEY}=true",
                "--label",
                f"{SESSION_LABEL_KEY}={validated_session_id}",
                "--label",
                f"{APP_LABEL_KEY}={APP_LABEL_VALUE}",
                "--label",
                f"{OWNER_LABEL_KEY}={_deployment_owner_id()}",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--network",
                settings.docker_network_mode or "none",
                "--memory",
                settings.docker_memory,
                "--cpus",
                str(settings.docker_cpus),
                "--pids-limit",
                str(settings.docker_pids_limit),
                "-v",
                f"{session_workspace}:{settings.docker_workspace_dir}:rw",
        ]
        # 用户级查询记忆目录：宿主机 workspace/_memory/<用户> → 容器 /wren-memory
        memory_mount = _memory_mount_for_session(validated_session_id)
        if memory_mount is not None:
            docker_args += ["-v", f"{memory_mount[0]}:{memory_mount[1]}:rw"]
        docker_args += [
                "-w",
                settings.docker_workspace_dir,
        ]
        if settings.docker_user:
            docker_args.extend(["--user", settings.docker_user])
        if settings.docker_read_only:
            docker_args.append("--read-only")
        if settings.docker_tmpfs_size:
            docker_args.extend(
                ["--tmpfs", f"/tmp:rw,nosuid,nodev,size={settings.docker_tmpfs_size}"]
            )
        docker_args.extend([settings.docker_image, *_keepalive_command()])
        _run_docker_command(docker_args)
        _touch_container(
            validated_session_id,
            container_name,
            created_by_app=True,
            started_by_app=True,
        )


def shutdown_execution_backend() -> None:
    if not settings.use_docker_execution or not settings.docker_stop_on_shutdown:
        return

    with _DOCKER_LOCK:
        for session_id, state in list(_SESSION_CONTAINERS.items()):
            try:
                _remove_container(state.container_name, remove=state.created_by_app)
            except RuntimeError as exc:
                logger.warning(
                    "shutdown container cleanup failed session_id=%s container=%s error=%s",
                    session_id,
                    state.container_name,
                    exc,
                )
                continue
            if _SESSION_CONTAINERS.get(session_id) is state:
                _SESSION_CONTAINERS.pop(session_id, None)


def _resolve_container_workdir(workspace_dir: str, session_id: str) -> str:
    workspace_root = resolve_workspace_root(session_id)
    exec_dir = Path(workspace_dir).resolve()
    relative_dir = exec_dir.relative_to(workspace_root)
    if str(relative_dir) in {"", "."}:
        return settings.docker_workspace_dir
    return str(PurePosixPath(settings.docker_workspace_dir) / relative_dir.as_posix())


# 容器内用户级查询记忆目录挂载点（宿主机 workspace/_memory/<用户> → /wren-memory）
_DOCKER_MEMORY_MOUNT_TARGET = "/wren-memory"


def _memory_mount_for_session(session_id: str) -> tuple[str, str] | None:
    """返回 (宿主机路径, 容器路径)；无法解析归属用户时不挂载。"""
    from .semantic_builder import user_memory_project_dir

    try:
        project = user_memory_project_dir(session_id)
    except Exception:
        return None
    if project is None:
        return None
    return str(project), _DOCKER_MEMORY_MOUNT_TARGET


def execute_python_in_docker(
    script_path: str,
    workspace_dir: str,
    timeout_sec: int,
    session_id: str,
    cancel_event: threading.Event | None = None,
) -> str:
    ensure_execution_backend_ready(session_id)
    container_name = _container_name_for_session(session_id)
    container_workdir = _resolve_container_workdir(workspace_dir, session_id)
    script_name = Path(script_path).name

    try:
        # session 语义层目录（容器内路径）；文件存在性由执行侧 bootstrap 校验
        wren_session_dir = (
            f"{settings.docker_workspace_dir}/.deepanalyze/wren"
        )
        # 用户级查询记忆目录：容器创建时按需挂载到 /wren-memory（未挂载时不注入 env，
        # wren_remember 会优雅降级返回 unavailable）
        docker_exec_args = [
            "docker",
            "exec",
            "-e",
            "MPLBACKEND=Agg",
            "-e",
            "MPLCONFIGDIR=/tmp/matplotlib",
            "-e",
            "QT_QPA_PLATFORM=offscreen",
            "-e",
            "HOME=/tmp",
            "-e",
            f"DEEPANALYZE_WREN_SESSION_DIR={wren_session_dir}",
        ]
        memory_mount = _memory_mount_for_session(session_id)
        if memory_mount is not None:
            docker_exec_args += ["-e", f"WREN_PROJECT_HOME={memory_mount[1]}"]
        docker_exec_args += [
            "-w",
            container_workdir,
            container_name,
            settings.docker_python_bin,
            script_name,
        ]
        process = subprocess.Popen(
            docker_exec_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        deadline = time.monotonic() + timeout_sec
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                cancelled = cancel_event is not None and cancel_event.is_set()
                timed_out = time.monotonic() >= deadline
                if not cancelled and not timed_out:
                    continue
                process.terminate()
                _run_docker_command(["stop", "-t", "1", container_name], check=False, timeout=10)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                if cancelled:
                    return "[Cancelled]: execution stopped by user"
                return f"[Timeout]: execution exceeded {timeout_sec} seconds"

        with _DOCKER_LOCK:
            _touch_container(
                session_id,
                container_name,
                created_by_app=False,
                started_by_app=False,
            )
        output = (stdout or "") + (stderr or "")
        if process.returncode:
            details = output.strip()
            suffix = f"\n{details}" if details else ""
            return f"[Error]: docker exec failed with exit code {process.returncode}{suffix}"
        return output
    except Exception as exc:
        return f"[Error]: {exc}"


def validate_execution_backend_configuration() -> None:
    execution_mode = settings.execution_mode.strip().lower()
    if execution_mode not in {"docker", "local"}:
        raise RuntimeError(f"Unsupported execution mode: {settings.execution_mode!r}")
    if not settings.use_docker_execution:
        if not settings.allow_unsafe_local_execution:
            raise RuntimeError(
                "Local execution is disabled. Set DEEPANALYZE_EXECUTION_MODE=docker "
                "or explicitly set DEEPANALYZE_ALLOW_UNSAFE_LOCAL_EXECUTION=true "
                "for trusted development."
            )
        return
    if shutil.which("docker") is None:
        raise RuntimeError("Docker CLI was not found")
    _ensure_docker_daemon_available()
    _ensure_docker_image_available()
