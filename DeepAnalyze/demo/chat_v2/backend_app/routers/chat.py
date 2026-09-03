from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ..services.chat import (
    begin_session_run_stop_event,
    bot_stream,
    build_chat_runtime_config,
    release_session_run,
    request_stop,
    try_acquire_session_run,
    wait_for_session_run_release,
)
from ..services.execution_service import execute_managed_code
from ..services.docker_executor import release_session_container
from ..services.session_state import (
    clear_pending_continuation,
    load_pending_continuation,
    load_session_state,
    replace_messages,
    update_task_config,
    upsert_message,
)
from ..services.workspace import validate_session_id
from ..settings import settings


router = APIRouter()


@router.post("/execute")
async def execute_code_api(request: dict):
    code = request.get("code", "")
    session_id = validate_session_id(request.get("session_id", "default"))

    if not code:
        return {
            "success": False,
            "result": "Error: No code provided",
            "message": "Code execution failed",
        }

    session_lock = try_acquire_session_run(session_id)
    if session_lock is None:
        raise HTTPException(status_code=409, detail="Session already has an active execution")
    stop_event = begin_session_run_stop_event(session_id)
    try:
        outcome = await run_in_threadpool(
            execute_managed_code,
            code,
            session_id,
            source="manual",
            instruction=str(request.get("instruction") or ""),
            original_code=str(request.get("original_code") or ""),
            cancel_event=stop_event,
        )
        message_id = f"manual-run-{outcome.run_id}"
        upsert_message(
            session_id,
            {
                "id": message_id,
                "role": "assistant",
                "content": outcome.trace_content,
            },
        )
        return {
            "success": outcome.success,
            "result": outcome.result,
            "message": (
                "Code executed successfully" if outcome.success else "Code execution failed"
            ),
            "trace_content": outcome.trace_content,
            "message_id": message_id,
            "execution": outcome.to_dict(),
        }
    except Exception as exc:
        return {
            "success": False,
            "result": f"Error: {exc}",
            "message": "Code execution failed",
        }
    finally:
        release_session_run(session_id, session_lock)


@router.post("/chat/completions")
async def chat(body: dict = Body(...)):
    messages = body.get("messages", [])
    session_messages = body.get("session_messages")
    if not isinstance(session_messages, list):
        session_messages = messages
    requested_workspace = body.get("workspace")
    workspace = requested_workspace if isinstance(requested_workspace, list) else []
    session_id = validate_session_id(body.get("session_id", "default"))
    try:
        runtime_config = build_chat_runtime_config(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    interaction_mode = "manual" if body.get("interaction_mode") == "manual" else "auto"
    resume_pending = body.get("resume_pending") is True
    pending_continuation = load_pending_continuation(session_id) if resume_pending else None
    if resume_pending and pending_continuation is None:
        raise HTTPException(status_code=409, detail="No paused analysis is available")
    if not resume_pending:
        clear_pending_continuation(session_id)

    existing_task = load_session_state(session_id).get("task_config") or {}
    latest_instruction = (
        str(existing_task.get("instruction") or "")
        if resume_pending
        else next(
            (
                str(message.get("content") or "")
                for message in reversed(session_messages)
                if message.get("role") == "user"
            ),
            "",
        )
    )
    state = update_task_config(
        session_id,
        {
            "instruction": latest_instruction,
            "selected_files": workspace,
            "provider": runtime_config.provider,
            "model": runtime_config.model,
            "temperature": runtime_config.temperature,
            "system_prompt": str(body.get("system_prompt") or ""),
            "ui_language": body.get("ui_language", ""),
            "interaction_mode": interaction_mode,
        },
    )
    workspace = (
        state["task_config"]["selected_files"]
        if isinstance(requested_workspace, list)
        else None
    )
    replace_messages(session_id, session_messages)
    assistant_message_id = str(
        body.get("assistant_message_id") or f"assistant-{datetime.now().timestamp()}"
    )

    def generate():
        assistant_parts: list[str] = []
        try:
            for delta_content in bot_stream(
                messages,
                workspace,
                session_id,
                runtime_config,
                interaction_mode=interaction_mode,
                resume_state=pending_continuation,
                additional_instruction=str(body.get("additional_instruction") or ""),
            ):
                assistant_parts.append(delta_content)
                chunk = {
                    "id": "chatcmpl-stream",
                    "object": "chat.completion.chunk",
                    "created": 1677652288,
                    "model": runtime_config.model or settings.model_path,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": delta_content},
                            "finish_reason": None,
                        }
                    ],
                }
                yield json.dumps(chunk) + "\n"
        except GeneratorExit:
            # Client disconnected: stop the analysis instead of letting it run on.
            request_stop(session_id)
            raise
        finally:
            if assistant_parts:
                upsert_message(
                    session_id,
                    {
                        "id": assistant_message_id,
                        "role": "assistant",
                        "content": "".join(assistant_parts),
                    },
                )

        end_chunk = {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1677652288,
            "model": runtime_config.model or settings.model_path,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "deepanalyze": {
                "interaction_status": (
                    "awaiting_user"
                    if load_pending_continuation(session_id) is not None
                    else "idle"
                ),
                "interaction_mode": interaction_mode,
            },
        }
        yield json.dumps(end_chunk) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/stop")
async def stop_chat(body: dict = Body(default={})):
    session_id = validate_session_id(body.get("session_id", "default"))
    await run_in_threadpool(request_stop, session_id)
    released = await run_in_threadpool(
        wait_for_session_run_release,
        session_id,
        settings.model_stream_read_timeout_sec + 5,
    )
    if not released:
        raise HTTPException(
            status_code=504,
            detail="Timed out waiting for the active analysis to stop",
        )
    try:
        container_released = await run_in_threadpool(release_session_container, session_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Analysis stopped, but the execution container could not be released",
        ) from exc
    return {
        "message": "analysis stopped",
        "session_id": session_id,
        "stopped": True,
        "container_released": container_released,
    }
