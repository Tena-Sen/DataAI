from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .routers.auth import COOKIE_NAME, router as auth_router
from .routers.chat import router as chat_router
from .routers.code_editing import router as code_editing_router
from .routers.export import router as export_router
from .routers.session import router as session_router
from .routers.user import router as user_router
from .routers.workspace import router as workspace_router
from .services.auth import current_user, store
from .services.docker_executor import (
    cleanup_idle_containers,
    shutdown_execution_backend,
    validate_execution_backend_configuration,
)

logger = logging.getLogger(__name__)

_REAPER_INTERVAL_SEC = 60


async def _idle_container_reaper() -> None:
    while True:
        await asyncio.sleep(_REAPER_INTERVAL_SEC)
        try:
            await run_in_threadpool(cleanup_idle_containers)
        except Exception as exc:  # pragma: no cover - best-effort reclamation
            logger.warning("idle container reaper failed: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_execution_backend_configuration()
    reaper_task = asyncio.create_task(_idle_container_reaper())
    try:
        yield
    finally:
        reaper_task.cancel()
        with suppress(asyncio.CancelledError):
            await reaper_task
        shutdown_execution_backend()


class AuthMiddleware:
    """统一认证中间件：/auth 路径放行，其余请求要求有效 token（Cookie 或 Bearer）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/auth" or path.startswith("/auth/"):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            header = request.headers.get("authorization", "")
            if header.lower().startswith("bearer "):
                token = header[7:].strip()
        username = store.resolve_token(token) if token else None
        if username is None:
            response = JSONResponse(
                {"detail": "Not authenticated"}, status_code=401
            )
            await response(scope, receive, send)
            return
        current_user.set(username)
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuthMiddleware)
    app.include_router(auth_router)
    app.include_router(workspace_router)
    app.include_router(chat_router)
    app.include_router(code_editing_router)
    app.include_router(export_router)
    app.include_router(session_router)
    app.include_router(user_router)
    return app


app = create_app()
