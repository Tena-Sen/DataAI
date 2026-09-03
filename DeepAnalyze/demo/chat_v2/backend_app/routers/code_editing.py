from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..services.chat import build_chat_runtime_config
from ..services.code_editing import edit_code_with_llm


router = APIRouter()


@router.post("/code/edit")
async def edit_code(body: dict = Body(...)):
    code = str(body.get("code") or "")
    instruction = str(body.get("instruction") or "")
    try:
        runtime_config = build_chat_runtime_config(body)
        result = await run_in_threadpool(
            edit_code_with_llm,
            code,
            instruction,
            runtime_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "code": result.code,
        "raw_response": result.raw_response,
    }
