"""语义层浏览/编辑 API：前端"语义层"面板的数据源。

- GET  /semantic/layer      表/列/含义清单（触发惰性构建）
- PUT  /semantic/describe   登记列含义（前端手动编辑与 AI 编目共用同一存储）
- GET  /semantic/preview    表数据采样预览（只读 DuckDB）
- GET  /semantic/memory     用户级 NL→SQL 查询记忆列表
- DELETE /semantic/memory   删除一条查询记忆

session 归属校验由 get_session_workspace → validate_session_id 统一完成。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from ..services.semantic_builder import (
    add_memory_pair,
    ensure_semantic_layer,
    forget_memory_pair,
    list_memory_pairs,
    load_excluded,
    preview_table,
    remove_table,
    restore_table,
    save_column_descriptions,
    update_memory_pair,
)
from ..services.workspace import validate_session_id

router = APIRouter(prefix="/semantic", tags=["semantic"])


@router.get("/layer")
async def semantic_layer(session_id: str = Query("default")):
    layer = await run_in_threadpool(ensure_semantic_layer, session_id)
    excluded = await run_in_threadpool(load_excluded, session_id)
    return {
        "models": layer.models if layer else [],
        "excluded": sorted(excluded),
        "relationships": layer.relationships if layer else [],
    }


@router.put("/describe")
async def describe_columns(
    body: dict = Body(
        ...,
        examples=[
            {
                "session_id": "default",
                "table": "销售流水",
                "descriptions": {"金额": "订单金额，单位元"},
            }
        ],
    ),
):
    session_id = str(body.get("session_id") or "default")
    table = str(body.get("table") or "")
    descriptions = body.get("descriptions")
    if not isinstance(descriptions, dict) or not descriptions:
        raise HTTPException(status_code=400, detail="descriptions must be a non-empty map")
    # 先触发归属校验（非本人 session → 403 / 非法 ID → 400）
    await run_in_threadpool(ensure_semantic_layer, session_id)
    status = await run_in_threadpool(
        save_column_descriptions, session_id, table, descriptions
    )
    if status.startswith("wren_describe failed"):
        raise HTTPException(status_code=500, detail=status)
    layer = await run_in_threadpool(ensure_semantic_layer, session_id)
    return {"status": status, "models": layer.models if layer else []}


@router.get("/preview")
async def semantic_preview(
    table: str = Query(...),
    session_id: str = Query("default"),
    limit: int = Query(20, ge=1, le=200),
):
    try:
        return await run_in_threadpool(preview_table, session_id, table, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/table")
async def delete_semantic_table(
    table: str = Query(...),
    session_id: str = Query("default"),
):
    """从语义层删除表（排除清单持久化；原上传文件不动，可恢复）。"""
    status = await run_in_threadpool(remove_table, session_id, table)
    if status.startswith("remove failed"):
        raise HTTPException(status_code=400, detail=status)
    layer = await run_in_threadpool(ensure_semantic_layer, session_id)
    excluded = await run_in_threadpool(load_excluded, session_id)
    return {
        "status": status,
        "models": layer.models if layer else [],
        "excluded": sorted(excluded),
    }


@router.put("/restore")
async def restore_semantic_table(
    body: dict = Body(..., examples=[{"session_id": "default", "table": "销售流水"}]),
):
    session_id = str(body.get("session_id") or "default")
    table = str(body.get("table") or "")
    status = await run_in_threadpool(restore_table, session_id, table)
    if status.startswith("restore failed"):
        raise HTTPException(status_code=400, detail=status)
    layer = await run_in_threadpool(ensure_semantic_layer, session_id)
    excluded = await run_in_threadpool(load_excluded, session_id)
    return {
        "status": status,
        "models": layer.models if layer else [],
        "excluded": sorted(excluded),
    }


@router.get("/memory")
async def memory_list(session_id: str = Query("default")):
    """用户级查询记忆列表（session_id 仅用于归属校验与解析用户）。"""
    await run_in_threadpool(validate_session_id, session_id)
    pairs = await run_in_threadpool(list_memory_pairs, session_id)
    return {"pairs": pairs}


@router.post("/memory")
async def memory_add(
    body: dict = Body(
        ...,
        examples=[
            {
                "session_id": "default",
                "nl": "各区域的销售总额",
                "sql": "SELECT 区域, SUM(金额) FROM 销售流水 GROUP BY 区域",
                "datasource": "销售流水.csv",
            }
        ],
    ),
):
    """手动添加一条查询记忆。"""
    session_id = str(body.get("session_id") or "default")
    await run_in_threadpool(validate_session_id, session_id)
    result = await run_in_threadpool(
        add_memory_pair,
        session_id,
        str(body.get("nl") or ""),
        str(body.get("sql") or ""),
        str(body.get("datasource") or ""),
    )
    if str(result.get("status", "")).startswith("add failed"):
        raise HTTPException(status_code=400, detail=result["status"])
    pairs = await run_in_threadpool(list_memory_pairs, session_id)
    return {**result, "pairs": pairs}


@router.put("/memory")
async def memory_update(
    body: dict = Body(
        ...,
        examples=[
            {
                "session_id": "default",
                "file": "query-abc123.md",
                "nl": "各区域的销售总额（含退款）",
                "sql": "SELECT 区域, SUM(净额) FROM 销售流水 GROUP BY 区域",
                "datasource": "销售流水.csv",
            }
        ],
    ),
):
    """编辑一条查询记忆（nl 变化时文件名随 hash 改变）。"""
    session_id = str(body.get("session_id") or "default")
    await run_in_threadpool(validate_session_id, session_id)
    result = await run_in_threadpool(
        update_memory_pair,
        session_id,
        str(body.get("file") or ""),
        str(body.get("nl") or ""),
        str(body.get("sql") or ""),
        str(body.get("datasource") or ""),
    )
    if str(result.get("status", "")).startswith("update failed"):
        raise HTTPException(status_code=400, detail=result["status"])
    pairs = await run_in_threadpool(list_memory_pairs, session_id)
    return {**result, "pairs": pairs}


@router.delete("/memory")
async def memory_forget(
    file: str = Query(...),
    session_id: str = Query("default"),
):
    """删除一条查询记忆（按文件名）。"""
    await run_in_threadpool(validate_session_id, session_id)
    status = await run_in_threadpool(forget_memory_pair, session_id, file)
    if status.startswith("forget failed"):
        raise HTTPException(status_code=400, detail=status)
    pairs = await run_in_threadpool(list_memory_pairs, session_id)
    return {"status": status, "pairs": pairs}
