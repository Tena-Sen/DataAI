from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from contextvars import ContextVar
from pathlib import Path

from fastapi import HTTPException

from ..settings import settings

USERNAME_PATTERN = re.compile(r"^[a-z0-9_-]{3,32}$")
# 已归属用户的 session 目录前缀：u{username}__
OWNED_SESSION_PATTERN = re.compile(r"^u[a-z0-9_-]{1,32}__")
PBKDF2_ITERATIONS = 100_000
TOKEN_MAX_AGE_SEC = 30 * 24 * 3600

current_user: ContextVar[str | None] = ContextVar("current_user", default=None)


def get_current_user() -> str | None:
    return current_user.get()


def session_prefix(username: str) -> str:
    return f"u{username}__"


class AuthStore:
    """用户与令牌存储（JSON 文件，原子写，线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        base = Path(settings.auth_dir)
        base.mkdir(parents=True, exist_ok=True)
        self._users_path = base / "users.json"
        self._tokens_path = base / "tokens.json"

    @staticmethod
    def _read_json(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    @staticmethod
    def _write_json(path: Path, payload) -> None:
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)

    def _load_users(self) -> dict:
        payload = self._read_json(self._users_path, {})
        return payload if isinstance(payload, dict) else {}

    def _load_tokens(self) -> dict:
        payload = self._read_json(self._tokens_path, {})
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
        )
        return digest.hex()

    def register(self, username: str, password: str) -> str:
        username = str(username or "").strip().lower()
        if not USERNAME_PATTERN.fullmatch(username):
            raise HTTPException(
                status_code=400,
                detail="用户名只能包含小写字母、数字、下划线和连字符，长度 3-32",
            )
        if len(password or "") < 4:
            raise HTTPException(status_code=400, detail="密码至少 4 位")
        with self._lock:
            users = self._load_users()
            if username in users:
                raise HTTPException(status_code=409, detail="用户名已存在")
            salt = secrets.token_bytes(16)
            users[username] = {
                "salt": salt.hex(),
                "hash": self._hash_password(password, salt),
                "created_at": time.time(),
            }
            self._write_json(self._users_path, users)
            if len(users) == 1:
                # 首个注册用户：认领历史无主 session
                claim_legacy_sessions(username)
            return self._issue_token(username, persist=True)

    def login(self, username: str, password: str) -> str:
        username = str(username or "").strip().lower()
        with self._lock:
            users = self._load_users()
            record = users.get(username)
        if record is None:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        salt = bytes.fromhex(record["salt"])
        expected = record["hash"]
        actual = self._hash_password(password or "", salt)
        if not hmac.compare_digest(expected, actual):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        with self._lock:
            return self._issue_token(username, persist=True)

    def _issue_token(self, username: str, *, persist: bool) -> str:
        token = secrets.token_hex(32)
        with self._lock:
            tokens = self._load_tokens()
            now = time.time()
            # 顺带清理过期 token
            tokens = {
                key: value
                for key, value in tokens.items()
                if now - value.get("created_at", 0) < TOKEN_MAX_AGE_SEC
            }
            tokens[token] = {"username": username, "created_at": now}
            if persist:
                self._write_json(self._tokens_path, tokens)
        return token

    def resolve_token(self, token: str | None) -> str | None:
        if not token:
            return None
        with self._lock:
            tokens = self._load_tokens()
            record = tokens.get(token)
        if not record:
            return None
        if time.time() - record.get("created_at", 0) >= TOKEN_MAX_AGE_SEC:
            self.revoke_token(token)
            return None
        return record.get("username")

    def revoke_token(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            tokens = self._load_tokens()
            if token in tokens:
                del tokens[token]
                self._write_json(self._tokens_path, tokens)

    def user_exists(self, username: str) -> bool:
        with self._lock:
            return username in self._load_users()

    def list_sessions(self, username: str) -> list[dict]:
        """列出该用户名下的所有会话（按更新时间倒序）。"""
        prefix = session_prefix(username)
        tombstones = load_tombstones(username)
        workspace_root = Path(settings.workspace_base_dir)
        state_root = workspace_root / ".session_state"
        sessions: list[dict] = []
        if not workspace_root.exists():
            return sessions
        for child in workspace_root.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not child.name.startswith(prefix):
                continue
            # 已删除的会话：即使目录被轮询请求意外重建，也不再出现在列表中
            if child.name in tombstones:
                continue
            state_path = state_root / child.name / "session.json"
            instruction = ""
            custom_title = ""
            message_count = 0
            updated_at = ""
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    task = state.get("task_config") or {}
                    instruction = str(task.get("instruction") or "").strip()
                    custom_title = str(state.get("custom_title") or "").strip()
                    messages = state.get("messages") or []
                    message_count = len(messages)
                    if not instruction and messages:
                        first_user = next(
                            (m for m in messages if m.get("role") == "user"),
                            None,
                        )
                        if first_user:
                            instruction = str(first_user.get("content") or "").strip()[:80]
                    updated_at = str(state.get("updated_at") or "")
                except (OSError, ValueError):
                    pass
            sessions.append(
                {
                    "session_id": child.name,
                    "instruction": instruction[:80],
                    "custom_title": custom_title[:80],
                    "message_count": message_count,
                    "updated_at": updated_at,
                }
            )
        sessions.sort(key=lambda item: item["updated_at"], reverse=True)
        return sessions


store = AuthStore()


# ===== 已删除会话墓碑（防止轮询请求重建目录后会话复活） =====


def _tombstones_path(username: str) -> Path:
    base = Path(settings.auth_dir) / "deleted_sessions"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{username}.json"


def load_tombstones(username: str) -> set[str]:
    try:
        payload = json.loads(_tombstones_path(username).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(item) for item in payload} if isinstance(payload, list) else set()


def add_tombstone(username: str, session_id: str) -> None:
    tombstones = load_tombstones(username)
    tombstones.add(session_id)
    with store._lock:
        path = _tombstones_path(username)
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(sorted(tombstones), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)


# ===== 用户级模型配置存储 =====

_MODEL_CONFIG_FIELDS = {
    "provider",
    "model",
    "api_base",
    "api_key",
    "heywhale_api_key",
    "temperature",
}


def _model_config_path(username: str) -> Path:
    base = Path(settings.auth_dir) / "model_configs"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{username}.json"


def load_model_config(username: str) -> dict:
    path = _model_config_path(username)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items() if key in _MODEL_CONFIG_FIELDS}


def save_model_config(username: str, config: dict) -> dict:
    now = time.time()
    normalized = {
        "provider": str(config.get("provider") or "local"),
        "model": str(config.get("model") or ""),
        "api_base": str(config.get("api_base") or ""),
        "api_key": str(config.get("api_key") or ""),
        "heywhale_api_key": str(config.get("heywhale_api_key") or ""),
        "temperature": config.get("temperature"),
        "updated_at": now,
    }
    with store._lock:
        path = _model_config_path(username)
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)
    return {key: value for key, value in normalized.items() if key != "updated_at"}


def claim_legacy_sessions(username: str) -> list[str]:
    """把历史无主 session 目录（无 u{user}__ 前缀）迁移给该用户。

    - workspace/{sid} 目录重命名为 workspace/u{user}__{sid}
    - .session_state/{sid}/session.json 同步迁移，并替换内容中的旧 session_id
    """
    prefix = session_prefix(username)
    workspace_root = Path(settings.workspace_base_dir)
    if not workspace_root.exists():
        return []
    state_root = workspace_root / ".session_state"
    claimed: list[str] = []
    for child in sorted(workspace_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if OWNED_SESSION_PATTERN.match(child.name):
            continue
        old_id = child.name
        new_id = f"{prefix}{old_id}"
        new_dir = workspace_root / new_id
        if new_dir.exists():
            continue
        child.rename(new_dir)

        old_state_dir = state_root / old_id
        if old_state_dir.is_dir():
            new_state_dir = state_root / new_id
            if not new_state_dir.exists():
                old_state_dir.rename(new_state_dir)
            state_file = new_state_dir / "session.json"
            if state_file.exists():
                try:
                    text = state_file.read_text(encoding="utf-8")
                    state_file.write_text(
                        text.replace(old_id, new_id), encoding="utf-8"
                    )
                except OSError:
                    pass
        claimed.append(new_id)
    return claimed
