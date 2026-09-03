from __future__ import annotations

import shutil

from fastapi import APIRouter, Body, HTTPException, Query

from ..services.auth import add_tombstone, get_current_user, store
from ..services.session_state import (
    clear_pending_continuation,
    load_public_session_state,
    replace_messages,
    set_custom_title,
    update_task_config,
)
from ..services.workspace import resolve_workspace_root, validate_session_id


router = APIRouter()


@router.get("/session/state")
async def get_session_state(session_id: str = Query("default")):
    return load_public_session_state(session_id)


@router.get("/sessions/list")
async def list_sessions():
    username = get_current_user()
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"sessions": store.list_sessions(username)}


@router.put("/sessions/rename")
async def rename_session(body: dict = Body(...)):
    username = get_current_user()
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session_id = str(body.get("session_id") or "")
    title = str(body.get("title") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    # validate_session_id 在 set_custom_title 内部校验归属：非本人会话返回 403
    state = set_custom_title(session_id, title)
    return {
        "session_id": state["session_id"],
        "custom_title": state.get("custom_title") or "",
    }


@router.delete("/sessions/delete")
async def delete_session(session_id: str = Query(...)):
    username = get_current_user()
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # validate_session_id 校验归属：非本人会话返回 403
    sid = validate_session_id(session_id)
    workspace_root = resolve_workspace_root(sid)
    state_dir = workspace_root.parent / ".session_state" / sid
    try:
        if workspace_root.exists():
            shutil.rmtree(workspace_root)
        if state_dir.exists():
            shutil.rmtree(state_dir)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"删除失败，文件可能被占用：{exc}"
        )
    # 写入墓碑：即使目录被残留轮询请求重建，也不再出现在会话列表
    add_tombstone(username, sid)
    return {"session_id": sid, "deleted": True}


@router.delete("/session/pending")
async def delete_session_pending(session_id: str = Query("default")):
    clear_pending_continuation(session_id)
    return {"session_id": session_id, "status": "idle"}


@router.put("/session/messages")
async def put_session_messages(body: dict = Body(...)):
    return replace_messages(
        body.get("session_id", "default"),
        body.get("messages") or [],
    )


@router.put("/session/task")
async def put_session_task(body: dict = Body(...)):
    return update_task_config(
        body.get("session_id", "default"),
        body.get("task_config") or {},
    )
