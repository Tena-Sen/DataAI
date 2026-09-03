from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request, Response

from ..services.auth import TOKEN_MAX_AGE_SEC, store

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "da_token"


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=TOKEN_MAX_AGE_SEC,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _read_token(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


@router.post("/register")
async def register(body: dict = Body(...), response: Response = None):  # type: ignore[assignment]
    token = store.register(
        str(body.get("username") or ""),
        str(body.get("password") or ""),
    )
    username = str(body.get("username") or "").strip().lower()
    _set_auth_cookie(response, token)
    return {"username": username}


@router.post("/login")
async def login(body: dict = Body(...), response: Response = None):  # type: ignore[assignment]
    token = store.login(
        str(body.get("username") or ""),
        str(body.get("password") or ""),
    )
    username = str(body.get("username") or "").strip().lower()
    _set_auth_cookie(response, token)
    return {"username": username}


@router.post("/logout")
async def logout(request: Request, response: Response):
    store.revoke_token(_read_token(request))
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    username = store.resolve_token(_read_token(request))
    if username is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"username": username}
