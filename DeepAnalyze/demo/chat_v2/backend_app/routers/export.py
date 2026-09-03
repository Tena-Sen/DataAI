from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ..services.exporter import export_report_from_body


router = APIRouter()


@router.post("/export/report")
async def export_report(body: dict = Body(...)):
    try:
        # pandoc/xelatex can take tens of seconds; keep the event loop free.
        return JSONResponse(await run_in_threadpool(export_report_from_body, body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
