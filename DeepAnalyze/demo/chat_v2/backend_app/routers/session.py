from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query

from ..services.auth import get_current_user, store
from ..services.session_state import (
    clear_pending_continuation,
    load_public_session_state,
    replace_messages,
    update_task_config,
)


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
