from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, Body, HTTPException

from ..services.auth import get_current_user, load_model_config, save_model_config
from ..services.chat import (
    FIXED_MODEL_NAME,
    HEYWHALE_API_BASE,
    HEYWHALE_BACKUP_CHAT_COMPLETIONS_URL,
)
from ..settings import settings

router = APIRouter(prefix="/user", tags=["user"])

_TEST_TIMEOUT_SEC = 20


def _require_username() -> str:
    username = get_current_user()
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return username


@router.get("/model-config")
async def get_model_config():
    username = _require_username()
    config = load_model_config(username)
    return {"config": config}


@router.put("/model-config")
async def put_model_config(body: dict = Body(...)):
    username = _require_username()
    saved = save_model_config(username, body.get("config") or {})
    return {"config": saved}


@router.post("/model-config/test")
async def test_model_config(body: dict = Body(default={})):
    username = _require_username()
    # 优先测试请求体里的配置；否则测试已保存的配置
    payload = body.get("config")
    if not isinstance(payload, dict) or not payload:
        payload = load_model_config(username)

    provider = str(payload.get("provider") or "local").strip().lower()
    if provider not in {"local", "heywhale", "custom"}:
        provider = "local"
    api_key = str(payload.get("api_key") or "").strip()
    heywhale_key = str(payload.get("heywhale_api_key") or "").strip()
    api_base = str(payload.get("api_base") or "").strip().rstrip("/")
    model = str(payload.get("model") or "").strip()

    if provider == "custom" and not api_base:
        return {
            "success": False,
            "detail": "Custom API base is required",
        }

    if provider == "local":
        return _test_local(model or settings.model_path or FIXED_MODEL_NAME)
    if provider == "heywhale":
        if not heywhale_key:
            return {"success": False, "detail": "HeyWhale API key is required"}
        return _test_http_endpoint(HEYWHALE_API_BASE, heywhale_key, FIXED_MODEL_NAME)
    return _test_http_endpoint(api_base, api_key, model or FIXED_MODEL_NAME)


def _test_local(model: str) -> dict:
    started = time.perf_counter()
    try:
        import openai

        client = openai.OpenAI(base_url=settings.api_base, api_key="dummy")
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=_TEST_TIMEOUT_SEC,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "success": True,
            "detail": f"local model '{model}' responded",
            "latency_ms": latency_ms,
            "model": model,
        }
    except Exception as exc:
        return {
            "success": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "model": model,
        }


def _test_http_endpoint(api_base: str, api_key: str, model: str) -> dict:
    urls = [f"{api_base}/chat/completions"]
    if api_base.rstrip("/") == HEYWHALE_API_BASE.rstrip("/"):
        urls.append(HEYWHALE_BACKUP_CHAT_COMPLETIONS_URL)

    last_detail = "unknown error"
    for url in urls:
        started = time.perf_counter()
        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            response = httpx.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "stream": False,
                },
                timeout=_TEST_TIMEOUT_SEC,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code == 200:
                try:
                    remote_model = response.json().get("model") or model
                except ValueError:
                    remote_model = model
                return {
                    "success": True,
                    "detail": f"'{model}' responded",
                    "latency_ms": latency_ms,
                    "model": remote_model,
                }
            last_detail = f"HTTP {response.status_code}: {response.text[:300]}"
        except httpx.HTTPError as exc:
            last_detail = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # pragma: no cover - defensive
            last_detail = f"{type(exc).__name__}: {exc}"
    return {"success": False, "detail": last_detail, "model": model}
