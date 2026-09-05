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
from .routers.semantic import router as semantic_router
from .routers.session import router as session_router
from .routers.user import router as user_router
from .routers.workspace import router as workspace_router
from .services.auth import current_user, store
from .services.docker_executor import (
    cleanup_idle_containers,
    shutdown_execution_backend,
    validate_execution_backend_configuration,
)
from .services.semantic_builder import prewarm_semantic_embedder
from .services.wren_service import start_wren_service, stop_wren_service
from .settings import settings

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
    # wren 查询常驻服务：省去每次查询的 CLI 进程启动开销（失败自动回退 CLI）
    await run_in_threadpool(start_wren_service)
    # 语义召回 embedding 模型预热（后台线程，不阻塞启动；失败回退词法匹配）
    prewarm_semantic_embedder()
    reaper_task = asyncio.create_task(_idle_container_reaper())
    try:
        yield
    finally:
        reaper_task.cancel()
        with suppress(asyncio.CancelledError):
            await reaper_task
        await run_in_threadpool(stop_wren_service)
        shutdown_execution_backend()


class AuthMiddleware:
    """统一认证中间件：/auth 路径放行，其余请求要求有效 token（Cookie 或 Bearer）。

    注意：CORSMiddleware 必须位于本中间件外层（见 create_app），预检 OPTIONS
    由它在最外层直接应答，本中间件短路返回的 401 也会被补上 CORS 头。
    """

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
    # 中间件按"洋葱"嵌套：后 add 的在外层。CORSMiddleware 必须最外层，
    # 否则 AuthMiddleware 短路返回的 401 不带 Access-Control-Allow-Origin，
    # 浏览器会把它当作请求失败，前端 fetch 直接抛异常（表现为"连接中断"）。
    app.add_middleware(AuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # 流式接口直连后端（绕开 Next dev 代理的响应体缓冲/超时），
        # 跨源带 Cookie 时 allow_origins 不能用 "*"，必须显式列出；
        # 正则额外放行局域网地址，支持手机/其他设备经 IP 访问前端。
        allow_origins=[
            f"http://localhost:{settings.frontend_port}",
            f"http://127.0.0.1:{settings.frontend_port}",
        ],
        allow_origin_regex=(
            r"^https?://("
            r"localhost"
            r"|127\.0\.0\.1"
            r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|192\.168\.\d{1,3}\.\d{1,3}"
            r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
            r")(:\d{1,5})?$"
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router)
    app.include_router(workspace_router)
    app.include_router(chat_router)
    app.include_router(code_editing_router)
    app.include_router(export_router)
    app.include_router(semantic_router)
    app.include_router(session_router)
    app.include_router(user_router)
    return app


app = create_app()
