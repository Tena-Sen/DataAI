from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .workspace import (
    INTERNAL_WORKSPACE_DIRNAME,
    resolve_workspace_path,
    resolve_workspace_root,
    validate_session_id,
)


STATE_FILENAME = "session.json"
STATE_SCHEMA_VERSION = 2
MAX_STORED_MESSAGES = 1000
MAX_STORED_EXECUTIONS = 200
_STATE_LOCKS: dict[str, threading.RLock] = {}
_STATE_LOCKS_GUARD = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_lock(session_id: str) -> threading.RLock:
    sid = validate_session_id(session_id)
    with _STATE_LOCKS_GUARD:
        lock = _STATE_LOCKS.get(sid)
        if lock is None:
            lock = threading.RLock()
            _STATE_LOCKS[sid] = lock
        return lock


def _state_path(session_id: str) -> Path:
    session_root = resolve_workspace_root(session_id)
    state_dir = session_root.parent / ".session_state" / validate_session_id(session_id)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / STATE_FILENAME


def _empty_state(session_id: str) -> dict[str, Any]:
    now = _utc_now()
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "session_id": validate_session_id(session_id),
        "task_config": {},
        "messages": [],
        "executions": [],
        "pending_continuation": None,
        "created_at": now,
        "updated_at": now,
    }


def load_session_state(session_id: str) -> dict[str, Any]:
    sid = validate_session_id(session_id)
    with _state_lock(sid):
        path = _state_path(sid)
        if not path.exists():
            return _empty_state(sid)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _empty_state(sid)
        if not isinstance(payload, dict):
            return _empty_state(sid)
        baseline = _empty_state(sid)
        baseline.update(payload)
        baseline["session_id"] = sid
        baseline["messages"] = list(baseline.get("messages") or [])
        baseline["executions"] = list(baseline.get("executions") or [])
        baseline["task_config"] = dict(baseline.get("task_config") or {})
        pending_continuation = baseline.get("pending_continuation")
        baseline["pending_continuation"] = (
            dict(pending_continuation)
            if isinstance(pending_continuation, dict)
            else None
        )
        return baseline


def load_public_session_state(session_id: str) -> dict[str, Any]:
    state = load_session_state(session_id)
    pending = state.pop("pending_continuation", None)
    state["interaction_state"] = {
        "status": "awaiting_user" if pending else "idle",
        "paused_at": str((pending or {}).get("paused_at") or ""),
    }
    return state


def _save_session_state(session_id: str, state: dict[str, Any]) -> dict[str, Any]:
    sid = validate_session_id(session_id)
    with _state_lock(sid):
        path = _state_path(sid)
        payload = deepcopy(state)
        payload["schema_version"] = STATE_SCHEMA_VERSION
        payload["session_id"] = sid
        payload["updated_at"] = _utc_now()
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
        return payload


def _normalize_message(message: dict[str, Any]) -> dict[str, Any] | None:
    role = str(message.get("role") or "").strip().lower()
    if not role:
        sender = str(message.get("sender") or "").strip().lower()
        role = "user" if sender == "user" else "assistant" if sender == "ai" else ""
    if role not in {"user", "assistant"}:
        return None
    content = str(message.get("content") or "")
    if not content and not message.get("attachments"):
        return None
    return {
        "id": str(message.get("id") or f"{role}-{datetime.now().timestamp()}"),
        "role": role,
        "content": content,
        "timestamp": str(message.get("timestamp") or _utc_now()),
        "attachments": list(message.get("attachments") or []),
    }


def replace_messages(
    session_id: str,
    messages: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    sid = validate_session_id(session_id)
    with _state_lock(sid):
        state = load_session_state(sid)
        state["messages"] = [
            normalized
            for message in messages
            if isinstance(message, dict)
            and (normalized := _normalize_message(message)) is not None
        ][-MAX_STORED_MESSAGES:]
        return _save_session_state(sid, state)


def append_message(session_id: str, message: dict[str, Any]) -> dict[str, Any]:
    sid = validate_session_id(session_id)
    normalized = _normalize_message(message)
    if normalized is None:
        return load_session_state(sid)
    with _state_lock(sid):
        state = load_session_state(sid)
        state["messages"].append(normalized)
        state["messages"] = state["messages"][-MAX_STORED_MESSAGES:]
        return _save_session_state(sid, state)


def upsert_message(session_id: str, message: dict[str, Any]) -> dict[str, Any]:
    sid = validate_session_id(session_id)
    normalized = _normalize_message(message)
    if normalized is None:
        return load_session_state(sid)
    with _state_lock(sid):
        state = load_session_state(sid)
        message_id = normalized["id"]
        existing_index = next(
            (
                index
                for index, existing in enumerate(state["messages"])
                if existing.get("id") == message_id
            ),
            None,
        )
        if existing_index is None:
            state["messages"].append(normalized)
        else:
            state["messages"][existing_index] = normalized
        state["messages"] = state["messages"][-MAX_STORED_MESSAGES:]
        return _save_session_state(sid, state)


def validate_selected_files(session_id: str, paths: Iterable[str]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    workspace_root = resolve_workspace_root(session_id)
    for raw_path in paths or []:
        try:
            candidate = resolve_workspace_path(session_id, str(raw_path))
        except Exception:
            continue
        if not candidate.exists() or not candidate.is_file():
            continue
        if INTERNAL_WORKSPACE_DIRNAME in candidate.relative_to(workspace_root).parts:
            continue
        relative = candidate.relative_to(workspace_root).as_posix()
        if relative not in seen:
            selected.append(relative)
            seen.add(relative)
    return selected


def update_task_config(
    session_id: str,
    task_config: dict[str, Any],
) -> dict[str, Any]:
    sid = validate_session_id(session_id)
    selected_files = validate_selected_files(sid, task_config.get("selected_files") or [])
    interaction_mode = str(task_config.get("interaction_mode") or "auto").lower()
    if interaction_mode not in {"auto", "manual"}:
        interaction_mode = "auto"
    normalized = {
        "instruction": str(task_config.get("instruction") or ""),
        "selected_files": selected_files,
        "provider": str(task_config.get("provider") or "local"),
        "model": str(task_config.get("model") or ""),
        "temperature": task_config.get("temperature"),
        "system_prompt": str(
            task_config.get("system_prompt")
            or task_config.get("additional_requirements")
            or ""
        ),
        "ui_language": str(task_config.get("ui_language") or ""),
        "interaction_mode": interaction_mode,
        "updated_at": _utc_now(),
    }
    with _state_lock(sid):
        state = load_session_state(sid)
        state["task_config"] = normalized
        return _save_session_state(sid, state)


def save_pending_continuation(
    session_id: str,
    continuation: dict[str, Any],
) -> dict[str, Any]:
    sid = validate_session_id(session_id)
    conversation = [
        {
            "role": str(message.get("role") or ""),
            "content": str(message.get("content") or ""),
        }
        for message in continuation.get("conversation") or []
        if isinstance(message, dict)
        and str(message.get("role") or "") in {"system", "user", "assistant", "execute"}
    ]
    pending = {
        "conversation": conversation,
        "execution_output": str(continuation.get("execution_output") or ""),
        "round_count": max(0, int(continuation.get("round_count") or 0)),
        "code_execution_count": max(
            0,
            int(continuation.get("code_execution_count") or 0),
        ),
        "elapsed_seconds": max(
            0.0,
            float(continuation.get("elapsed_seconds") or 0.0),
        ),
        "paused_at": _utc_now(),
    }
    with _state_lock(sid):
        state = load_session_state(sid)
        state["pending_continuation"] = pending
        return _save_session_state(sid, state)


def load_pending_continuation(session_id: str) -> dict[str, Any] | None:
    pending = load_session_state(session_id).get("pending_continuation")
    return deepcopy(pending) if isinstance(pending, dict) else None


def clear_pending_continuation(session_id: str) -> dict[str, Any]:
    sid = validate_session_id(session_id)
    with _state_lock(sid):
        state = load_session_state(sid)
        state["pending_continuation"] = None
        return _save_session_state(sid, state)


def append_execution_record(
    session_id: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    sid = validate_session_id(session_id)
    with _state_lock(sid):
        state = load_session_state(sid)
        state["executions"].append(deepcopy(record))
        state["executions"] = state["executions"][-MAX_STORED_EXECUTIONS:]
        return _save_session_state(sid, state)
