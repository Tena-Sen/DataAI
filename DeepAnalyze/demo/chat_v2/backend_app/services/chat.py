from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx
import openai

from .execution import build_file_block
from .execution_service import execute_managed_code
from .docker_executor import ensure_execution_backend_ready, release_session_container
from .session_state import clear_pending_continuation, save_pending_continuation
from .action_protocol import (
    ProtocolValidationError,
    find_completed_action_end,
    mask_backticked_content,
    normalize_model_output,
)
from .workspace import (
    collect_file_info,
    get_session_workspace,
    register_generated_paths,
    resolve_workspace_path,
    uniquify_path,
    validate_session_id,
)
from ..settings import (
    CHINESE_MATPLOTLIB_BOOTSTRAP,
    WREN_QUERY_BOOTSTRAP,
    settings,
)
from .semantic_builder import (
    SemanticLayer,
    ensure_semantic_layer,
    recall_similar_queries,
)


client = openai.OpenAI(base_url=settings.api_base, api_key="dummy")
logger = logging.getLogger(__name__)
_STOP_EVENTS: dict[str, threading.Event] = {}
_STOP_EVENTS_LOCK = threading.Lock()
_SESSION_RUN_LOCKS: dict[str, threading.Lock] = {}
_SESSION_RUN_LOCKS_LOCK = threading.Lock()
_ACTIVE_STREAM_CLOSERS: dict[str, tuple[object, Callable[[], None]]] = {}
_ACTIVE_STREAM_CLOSERS_LOCK = threading.Lock()
HEYWHALE_API_BASE = (
    "https://www.heywhale.com/api/model/services/691d42c36c6dda33df0bf645/app/v1"
)
HEYWHALE_BACKUP_CHAT_COMPLETIONS_URL = (
    "https://www.heywhale.com/api/model/services/69b7c9d028cbfe8349df5924/app/v1/chat/completions"
)
HEYWHALE_STOP_SEQUENCES = ["</Code>", "</Answer>"]
EXECUTE_RESULT_PREFIX = "# Execute Result\n"
ADDITIONAL_INSTRUCTION_HEADING = "# Additional Instruction"
FIXED_MODEL_NAME = "DeepAnalyze-8B"
_FENCE_WITH_INFO_RE = re.compile(r"```[ \t]*[\w.+-]*[ \t]*\r?\n(.*?)```", re.DOTALL)
_FENCE_INLINE_RE = re.compile(r"```(?:python)?(.*?)```", re.DOTALL | re.IGNORECASE)
_ACTION_TAG_AT_START_RE = re.compile(
    r"^\s*</?[A-Za-z][^>]*>",
)
_MODEL_ACTION_TAG_AT_START_RE = re.compile(
    r"^<(?:Analyze|Understand|Code|Answer|ConsultWren)>",
)
_MODEL_ACTION_TAG_RE = re.compile(r"<(?:Analyze|Understand|Code|Answer|ConsultWren)>")
_MODEL_ACTION_CLOSE_TAG_RE = re.compile(r"</(?:Analyze|Understand|Code|Answer|ConsultWren)>")
@dataclass(frozen=True)
class ChatRuntimeConfig:
    provider: str = "local"
    temperature: float = 0.4
    model: str = settings.model_path
    api_key: str = ""
    api_base: str = ""


def _is_deepanalyze_model(model_name: str) -> bool:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return False
    return bool(re.search(r"deep[\s\-_]*analyze", normalized))


# ---------- 长对话上下文压缩 ----------
# conversation 每轮追加代码 + 执行输出（单轮输出上限 32KB），无压缩时 30 轮
# 可达数十万字符，超出模型窗口后请求失败/质量崩塌。策略：
#   1) 执行输出入 conversation 前先截断（保留头尾 + 行数说明）
#   2) 总量超预算时折叠最旧的代码轮次（Analyze/Understand 保留，Code 轮次
#      的 assistant 消息缩为一行摘要、执行输出缩为头尾采样）
# 最近 _COMPACT_KEEP_RECENT 轮始终保留原文；首轮 user prompt（含语义层清单）不动。

_CONTEXT_BUDGET_CHARS = 120_000  # ≈ 3-4 万 token（中文为主），给输出留余量
_CONTEXT_HARD_TRUNCATE_CHARS = 16_000  # 单条执行输出入上下文的上限
_COMPACT_KEEP_RECENT = 4  # 保底不折叠的最近消息数（assistant+user 至少 1 轮）


def _truncate_execution_output_for_context(text: str) -> str:
    """执行输出入 conversation 前的截断：保头尾，中间注明省略量。"""
    text = str(text or "")
    if len(text) <= _CONTEXT_HARD_TRUNCATE_CHARS:
        return text
    keep = _CONTEXT_HARD_TRUNCATE_CHARS // 2
    head = text[:keep].rstrip()
    tail = text[-keep:].lstrip()
    omitted = len(text) - len(head) - len(tail)
    return f"{head}\n\n... [执行输出已截断：中间省略 {omitted} 字符] ...\n\n{tail}"


def _message_is_recent_contextual(content: str) -> bool:
    """消息是否承载持续有效的上下文（语义层/记忆参考/编目指令）。"""
    for marker in (
        "# Semantic Layer",
        "# Query Memory",
        "# Data\n",
        "# Instruction\n",
    ):
        if marker in content:
            return True
    return False


def _compact_conversation(conversation: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """总量超预算时折叠旧的代码轮次；返回原列表（就地修改，避免引用失效）。

    折叠规则（从最旧往新扫描，直到总量回到预算内）：
    - assistant 消息含 <Code> → 摘要化（保留动作标签结构，正文缩为一行）
    - user 消息以 EXECUTE_RESULT_PREFIX 开头且很长 → 头尾采样
    - 承载持续上下文的消息（语义层/记忆/数据清单）永不折叠
    """
    total = sum(len(str(m.get("content") or "")) for m in conversation)
    if total <= _CONTEXT_BUDGET_CHARS:
        return conversation
    # 折叠执行输出时按缺口决定保留量：缺口越大压得越狠（1.2K-4K 头尾采样）
    overflow_ratio = min(1.0, (total - _CONTEXT_BUDGET_CHARS) / max(total, 1))
    keep = max(1_200, int(4_000 * (1.0 - overflow_ratio)))
    for index in range(len(conversation) - _COMPACT_KEEP_RECENT):
        if total <= _CONTEXT_BUDGET_CHARS:
            break
        message = conversation[index]
        content = str(message.get("content") or "")
        if not content or _message_is_recent_contextual(content):
            continue
        role = message.get("role")
        if role == "assistant" and "<Code>" in content:
            lines = [ln for ln in content.splitlines() if ln.strip()]
            first = lines[0][:120] if lines else ""
            new_content = (
                f"<Understand>\n[context compacted] 早期代码轮次已折叠以控制上下文长度。"
                f"该轮起始内容：{first}\n</Understand>"
            )
            conversation[index] = {"role": role, "content": new_content}
            total -= len(content) - len(new_content)
        elif role == "user" and content.startswith(EXECUTE_RESULT_PREFIX):
            if len(content) > keep * 2:
                head = content[:keep].rstrip()
                tail = content[-keep:].lstrip()
                omitted = len(content) - len(head) - len(tail)
                new_content = (
                    f"{head}\n... [执行结果已折叠：省略 {omitted} 字符] ...\n{tail}"
                )
                conversation[index] = {"role": role, "content": new_content}
                total -= len(content) - len(new_content)
    return conversation


def _build_execution_feedback_message(
    runtime_config: ChatRuntimeConfig,
    execution_output: str,
) -> dict[str, str]:
    if not _is_deepanalyze_model(runtime_config.model):
        return {
            "role": "user",
            "content": f"{EXECUTE_RESULT_PREFIX}{execution_output}",
        }
    return {"role": "execute", "content": execution_output}


def _append_additional_instruction(
    execution_output: str,
    instruction: str,
) -> str:
    normalized_instruction = str(instruction or "").strip()
    if not normalized_instruction:
        return execution_output
    normalized_output = str(execution_output or "").rstrip()
    separator = "\n\n" if normalized_output else ""
    return (
        f"{normalized_output}{separator}{ADDITIONAL_INSTRUCTION_HEADING}\n"
        f"{normalized_instruction}"
    )


def _get_or_create_stop_event(session_id: str) -> threading.Event:
    sid = validate_session_id(session_id)
    with _STOP_EVENTS_LOCK:
        event = _STOP_EVENTS.get(sid)
        if event is None:
            event = threading.Event()
            _STOP_EVENTS[sid] = event
        return event


def request_stop(session_id: str) -> None:
    sid = validate_session_id(session_id)
    _get_or_create_stop_event(sid).set()
    active_stream_closed = _close_active_stream(sid)
    logger.info(
        "analysis_stop_requested session_id=%s active_stream=%s",
        sid,
        active_stream_closed,
    )


def get_session_stop_event(session_id: str) -> threading.Event:
    return _get_or_create_stop_event(session_id)


def begin_session_run_stop_event(session_id: str) -> threading.Event:
    sid = validate_session_id(session_id)
    event = threading.Event()
    with _STOP_EVENTS_LOCK:
        _STOP_EVENTS[sid] = event
    return event


def _register_active_stream(
    session_id: str | None,
    close: Callable[[], None],
    cancel_event: threading.Event | None = None,
) -> object | None:
    if not session_id:
        return None
    sid = validate_session_id(session_id)
    token = object()
    with _ACTIVE_STREAM_CLOSERS_LOCK:
        if cancel_event is not None and cancel_event.is_set():
            should_close = True
        else:
            _ACTIVE_STREAM_CLOSERS[sid] = (token, close)
            should_close = False
    if should_close:
        close()
        return None
    return token


def _clear_active_stream(session_id: str | None, token: object | None) -> None:
    if not session_id or token is None:
        return
    sid = validate_session_id(session_id)
    with _ACTIVE_STREAM_CLOSERS_LOCK:
        current = _ACTIVE_STREAM_CLOSERS.get(sid)
        if current is not None and current[0] is token:
            _ACTIVE_STREAM_CLOSERS.pop(sid, None)


def _close_active_stream(session_id: str | None) -> bool:
    if not session_id:
        return False
    sid = validate_session_id(session_id)
    with _ACTIVE_STREAM_CLOSERS_LOCK:
        active_stream = _ACTIVE_STREAM_CLOSERS.pop(sid, None)
    if active_stream is None:
        return False

    def close_stream() -> None:
        try:
            active_stream[1]()
        except Exception as exc:
            logger.warning("active model stream close failed for %s: %s", sid, exc)

    threading.Thread(
        target=close_stream,
        daemon=True,
        name="chat-model-stream-close",
    ).start()
    return True


def _iter_stream_with_cancellation(
    stream_iter,
    stop_event: threading.Event,
    session_id: str,
):
    items: queue.Queue[tuple[str, Any]] = queue.Queue()

    def pump() -> None:
        try:
            for item in stream_iter:
                items.put(("item", item))
        except BaseException as exc:
            items.put(("error", exc))
        finally:
            items.put(("done", None))

    threading.Thread(target=pump, daemon=True, name="chat-model-stream").start()
    try:
        while not stop_event.is_set():
            try:
                kind, payload = items.get(timeout=0.1)
            except queue.Empty:
                continue
            if kind == "item":
                yield payload
                continue
            if kind == "error":
                raise payload
            break
    finally:
        _close_active_stream(session_id)


def _get_or_create_session_run_lock(session_id: str) -> threading.Lock:
    sid = validate_session_id(session_id)
    with _SESSION_RUN_LOCKS_LOCK:
        lock = _SESSION_RUN_LOCKS.get(sid)
        if lock is None:
            lock = threading.Lock()
            _SESSION_RUN_LOCKS[sid] = lock
        return lock


def try_acquire_session_run(session_id: str) -> threading.Lock | None:
    lock = _get_or_create_session_run_lock(session_id)
    return lock if lock.acquire(blocking=False) else None


def release_session_run(session_id: str, lock: threading.Lock) -> None:
    # Do NOT clear the stop event here: a stop request that lands in the gap
    # between run completion and release would be silently swallowed. The event
    # is cleared at the start of each new run instead.
    lock.release()


def wait_for_session_run_release(session_id: str, timeout_sec: float) -> bool:
    lock = _get_or_create_session_run_lock(session_id)
    acquired = lock.acquire(timeout=max(0.0, timeout_sec))
    if not acquired:
        return False
    lock.release()
    return True


def is_session_run_active(session_id: str) -> bool:
    """该会话当前是否有正在运行的分析（供前端校准运行状态，自愈卡死 spinner）。"""
    try:
        sid = validate_session_id(session_id)
    except ValueError:
        return False
    with _SESSION_RUN_LOCKS_LOCK:
        lock = _SESSION_RUN_LOCKS.get(sid)
    return bool(lock and lock.locked())


def _execution_status_block(kind: str, message: str) -> str:
    logger.warning("analysis_status kind=%s message=%s", kind, message)
    return f"\n<Execute>\n[{kind}]: {message}\n</Execute>\n"


def _normalize_temperature(value: Any) -> float:
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return 0.4
    return max(0.0, min(2.0, temperature))


def _prefix_initial_analyze_tag(content: str) -> str:
    """首轮输出未以已知动作标签开头时，只补齐 Analyze 开标签。"""
    raw = content or ""
    if not raw.strip() or _ACTION_TAG_AT_START_RE.match(raw):
        return raw
    leading_length = len(raw) - len(raw.lstrip())
    return f"{raw[:leading_length]}<Analyze>{raw[leading_length:]}"


@dataclass
class _InitialStreamState:
    synthetic_analyze_open: bool = False


def _prepare_initial_stream_deltas(
    deltas: list[str],
    state: _InitialStreamState,
) -> Iterable[str]:
    raw = "".join(deltas)
    leading = raw.lstrip()
    if not leading or _MODEL_ACTION_TAG_AT_START_RE.match(leading):
        yield from deltas
        return

    leading_length = len(raw) - len(leading)
    cursor = 0
    inserted = False
    for delta in deltas:
        next_cursor = cursor + len(delta)
        if inserted or leading_length > next_cursor:
            yield delta
            cursor = next_cursor
            continue

        offset = max(0, leading_length - cursor)
        before, after = delta[:offset], delta[offset:]
        if before:
            yield before
        yield "<Analyze>"
        state.synthetic_analyze_open = True
        inserted = True
        if after:
            yield from _format_initial_stream_delta(after, state)
        cursor = next_cursor

    if not inserted:
        yield "<Analyze>"
        state.synthetic_analyze_open = True


def _format_initial_stream_delta(
    delta: str,
    state: _InitialStreamState,
) -> Iterable[str]:
    if not state.synthetic_analyze_open:
        yield delta
        return

    masked = mask_backticked_content(delta)
    cursor = 0
    while cursor < len(delta):
        open_match = _MODEL_ACTION_TAG_RE.search(masked, cursor)
        close_match = _MODEL_ACTION_CLOSE_TAG_RE.search(masked, cursor)
        if open_match is None and close_match is None:
            yield delta[cursor:]
            return

        if close_match is not None and (
            open_match is None or close_match.start() <= open_match.start()
        ):
            if close_match.start() > cursor:
                yield delta[cursor : close_match.start()]
            yield delta[close_match.start() : close_match.end()]
            state.synthetic_analyze_open = False
            cursor = close_match.end()
            if cursor < len(delta):
                yield delta[cursor:]
            return

        if open_match.start() > cursor:
            yield delta[cursor : open_match.start()]
        yield "</Analyze>"
        state.synthetic_analyze_open = False
        yield delta[open_match.start() :]
        return


def build_chat_runtime_config(payload: dict[str, Any] | None) -> ChatRuntimeConfig:
    body = payload or {}
    provider = str(body.get("provider") or "local").strip().lower() or "local"
    if provider not in {"local", "heywhale", "custom"}:
        provider = "local"

    api_base = str(body.get("api_base") or "").strip()
    # 容错：用户配置漏写协议前缀时自动补 https://（否则 httpx 报
    # "Request URL is missing an 'http://' or 'https://' protocol"）
    if api_base and "://" not in api_base:
        api_base = f"https://{api_base}"
    if provider == "heywhale" and not api_base:
        api_base = HEYWHALE_API_BASE
    if provider == "custom" and not api_base:
        raise ValueError("Custom API base is required")

    if provider in {"local", "heywhale"}:
        model = FIXED_MODEL_NAME
    else:
        model = str(body.get("model") or FIXED_MODEL_NAME).strip() or FIXED_MODEL_NAME
    api_key = str(body.get("api_key") or "").strip()
    if provider == "heywhale" and not api_key:
        raise ValueError("HeyWhale API key is required")

    return ChatRuntimeConfig(
        provider=provider,
        temperature=_normalize_temperature(body.get("temperature")),
        model=model,
        api_key=api_key,
        api_base=api_base,
    )


def _iter_local_stream(
    conversation: list[dict[str, Any]],
    runtime_config: ChatRuntimeConfig,
    session_id: str | None = None,
    cancel_event: threading.Event | None = None,
):
    response = client.with_options(
        timeout=settings.model_stream_read_timeout_sec
    ).chat.completions.create(
        model=runtime_config.model,
        messages=conversation,
        temperature=runtime_config.temperature,
        stream=True,
        extra_body={
            "add_generation_prompt": False,
            "stop_token_ids": [151676, 151645],
            "max_new_tokens": 32768,
        },
    )
    close = getattr(response, "close", None)
    stream_token = (
        _register_active_stream(session_id, close, cancel_event)
        if callable(close)
        else None
    )
    try:
        for chunk in response:
            yield chunk.choices[0].delta.content if chunk.choices else None, chunk
    finally:
        _clear_active_stream(session_id, stream_token)
        if callable(close):
            close()


def _iter_heywhale_stream(
    conversation: list[dict[str, Any]],
    runtime_config: ChatRuntimeConfig,
    session_id: str | None = None,
    cancel_event: threading.Event | None = None,
):
    if not runtime_config.api_key:
        raise ValueError("HeyWhale API key is required")

    request_body = {
        "messages": conversation,
        "temperature": runtime_config.temperature,
        "stream": True,
        "stop": HEYWHALE_STOP_SEQUENCES,
    }

    primary_url = f"{runtime_config.api_base.rstrip('/')}/chat/completions"
    request_urls = [primary_url]
    if runtime_config.api_base.rstrip("/") == HEYWHALE_API_BASE.rstrip("/"):
        request_urls.append(HEYWHALE_BACKUP_CHAT_COMPLETIONS_URL)

    timeout = httpx.Timeout(settings.model_stream_read_timeout_sec, connect=10)
    with httpx.Client(timeout=timeout) as http_client:
        for idx, request_url in enumerate(request_urls):
            has_stream_output = False
            streamed_content = ""
            try:
                with http_client.stream(
                    "POST",
                    request_url,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {runtime_config.api_key}",
                    },
                    json=request_body,
                ) as response:
                    response.raise_for_status()
                    stream_token = _register_active_stream(
                        session_id,
                        response.close,
                        cancel_event,
                    )
                    try:
                        for raw_line in response.iter_lines():
                            if not raw_line:
                                continue
                            line = raw_line.strip()
                            if not line:
                                continue
                            if line.startswith("data:"):
                                line = line[5:].strip()
                            if line == "[DONE]":
                                break
                            try:
                                payload = json.loads(line)
                            except Exception:
                                continue
                            has_stream_output = True
                            choice = (payload.get("choices") or [{}])[0]
                            delta = (choice.get("delta") or {}).get("content")
                            finish_reason = choice.get("finish_reason")
                            if delta:
                                streamed_content += delta
                            yield delta, {"choices": [{"finish_reason": finish_reason}]}
                            if finish_reason == "stop":
                                if (
                                    streamed_content.rfind("<Code>")
                                    > streamed_content.rfind("</Code>")
                                ):
                                    yield "</Code>", {"choices": [{"finish_reason": None}]}
                                elif (
                                    streamed_content.rfind("<Answer>")
                                    > streamed_content.rfind("</Answer>")
                                ):
                                    yield "</Answer>", {"choices": [{"finish_reason": None}]}
                    finally:
                        _clear_active_stream(session_id, stream_token)
                return
            except httpx.HTTPError:
                if has_stream_output or idx >= len(request_urls) - 1:
                    raise
                continue


def _iter_custom_stream(
    conversation: list[dict[str, Any]],
    runtime_config: ChatRuntimeConfig,
    session_id: str | None = None,
    cancel_event: threading.Event | None = None,
):
    request_body = {
        "model": runtime_config.model,
        "messages": conversation,
        "temperature": runtime_config.temperature,
        "stream": True,
    }

    headers = {"Content-Type": "application/json"}
    if runtime_config.api_key:
        headers["Authorization"] = f"Bearer {runtime_config.api_key}"

    timeout = httpx.Timeout(settings.model_stream_read_timeout_sec, connect=10)
    with httpx.Client(timeout=timeout) as http_client:
        with http_client.stream(
            "POST",
            f"{runtime_config.api_base.rstrip('/')}/chat/completions",
            headers=headers,
            json=request_body,
        ) as response:
            response.raise_for_status()
            stream_token = _register_active_stream(
                session_id,
                response.close,
                cancel_event,
            )
            try:
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        payload = json.loads(line)
                    except Exception:
                        continue
                    choice = (payload.get("choices") or [{}])[0]
                    delta = (choice.get("delta") or {}).get("content")
                    finish_reason = choice.get("finish_reason")
                    yield delta, {"choices": [{"finish_reason": finish_reason}]}
            finally:
                _clear_active_stream(session_id, stream_token)


def _resolve_workspace_selection(
    workspace: Iterable[str] | None,
    workspace_dir: str,
) -> list[Path]:
    workspace_root = Path(workspace_dir).resolve()
    resolved_paths: list[Path] = []
    for item in workspace or []:
        candidate = Path(item)
        if candidate.is_absolute():
            candidate = candidate.resolve()
            if candidate != workspace_root and workspace_root not in candidate.parents:
                continue
        else:
            try:
                candidate = resolve_workspace_path(
                    workspace_root.name,
                    str(candidate),
                )
            except Exception:
                continue
        if candidate.exists() and candidate.is_file():
            resolved_paths.append(candidate)
    return resolved_paths


def _build_user_prompt(
    messages: list[dict[str, Any]],
    workspace: list[str],
    workspace_dir: str,
    *,
    use_all_files_when_empty: bool,
    session_id: str = "default",
) -> None:
    if not messages or messages[-1].get("role") != "user":
        return

    user_message = str(messages[-1].get("content") or "")
    selected_paths = _resolve_workspace_selection(workspace, workspace_dir)
    file_source: list[Path] | str = selected_paths
    if not selected_paths and use_all_files_when_empty:
        file_source = workspace_dir
    file_info = collect_file_info(file_source)
    if file_info:
        messages[-1]["content"] = f"# Instruction\n{user_message}\n\n# Data\n{file_info}"
    else:
        messages[-1]["content"] = f"# Instruction\n{user_message}"

    # session 语义层（上传数据自动构建）：注入表/列清单与 wren_query 用法
    session_layer = ensure_semantic_layer(session_id)
    if session_layer is not None:
        session_context = _build_session_semantic_context(session_layer)
        if session_context:
            messages[-1]["content"] += f"\n\n{session_context}"
        # 用户级查询记忆：召回与当前问题相似的历史 NL→SQL（跨会话复用，省重复摸索）
        # 传表名 + 源文件名（datasource 登记的是文件名，如 订单 (1).csv）
        match_sources = [
            model["name"] for model in session_layer.models
        ] + [
            model.get("source_file") for model in session_layer.models if model.get("source_file")
        ]
        try:
            recalled = recall_similar_queries(
                session_id, user_message, current_tables=match_sources, limit=3
            )
        except Exception:
            recalled = []
        # 观测点：召回了几条，便于排查"幻觉"是召回带来的还是模型自己编的
        logger.info(
            "memory.recalled session_id=%s kept=%d nls=%s",
            session_id,
            len(recalled),
            [str(p.get("nl") or "")[:40] for p in recalled],
        )
        if recalled:
            memory_lines = [
                "",
                "# Query Memory (历史查询参考，可能来自其他数据集)",
                "以下历史查询与当前问题相似。表名/列名可能与本会话不同：仅供参考，改写后先用 `wren_dry_run` 验证。",
            ]
            for pair in recalled:
                memory_lines.append(f"- 问题: {pair.get('nl')}")
                memory_lines.append(f"  SQL: {' '.join(str(pair.get('sql') or '').split())}")
            memory_lines.append(
                "采用这些参考后，请在最终答案对应的 wren_query 成功后调用 `wren_remember(\"<自然语言问题>\", \"<SQL>\", datasource=\"<数据文件名>\")` 登记 —— 把本轮最终 SQL（不是参考里的原 SQL）覆盖登记回去，这样下次就能直接召回本 session 真实可用的写法。"
            )
            messages[-1]["content"] += "\n".join(memory_lines)


_MAX_MODELS_IN_PROMPT = 15
_MAX_COLUMNS_IN_PROMPT = 30
_MAX_RELATIONSHIPS_IN_PROMPT = 10


def _build_session_semantic_context(layer: SemanticLayer) -> str:
    """session 语义层清单：表/列/含义 + wren_query 用法。

    列含义来自 AI 编目（wren_describe 写回的数据字典）；尚未编目时
    附上编目指引（先采样推断含义再分析），编目歧义向用户提问。
    """
    lines = [
        "# Semantic Layer (session data)",
        "本次上传的数据已自动注册为语义层（DuckDB 引擎），表名/列名与原文件一致（已清理为合法标识符，中文保留）。",
        "分析这些数据时：",
        '- `wren_query("<SQL>")` — 用 SQL 查询上传数据，如 `wren_query("SELECT 销售人员, SUM(金额) AS 总额 FROM 销售流水 GROUP BY 销售人员")`',
        '- `wren_dry_run("<SQL>")` — 执行前校验 SQL（不取数）',
        '- `wren_remember("<自然语言问题>", "<SQL>", datasource="<数据文件名>")` — **每次 wren_query 成功返回非空 DataFrame 后都必须调用一次**（同一轮多步仅在最终答案对应的 SQL 上登记一次）。判定标准：①该查询回答了用户本轮的核心问题；②SQL 引用了本 session 语义层中的表（`datasource` 填上传时的文件名，如 `销售明细.csv`）；③不是临时探查（如 SELECT * LIMIT 5）。登记后下次/跨 session 相似问题会自动作为参考召回，省去重复摸索',
        "大规模聚合、多表 JOIN 优先用 wren_query（比 pandas 逐块读更省内存）；需要复杂 Python 处理时仍可直接用 pandas 读原文件。两条路径数据一致。",
        "",
        "## 数据模型清单",
    ]
    cataloged_tables = 0
    shown_models = layer.models[:_MAX_MODELS_IN_PROMPT]
    for model in shown_models:
        lines.append(f"- **{model['name']}** — {model['description']}")
        columns = model["columns"]
        if any(c.get("desc") for c in columns):
            cataloged_tables += 1
        parts: list[str] = []
        for column in columns[:_MAX_COLUMNS_IN_PROMPT]:
            desc = column.get("desc")
            parts.append(
                f"{column['name']}（{desc}）" if desc else f"{column['name']} {column['type']}"
            )
        shown = ", ".join(parts)
        if len(columns) > _MAX_COLUMNS_IN_PROMPT:
            shown += f", …（共 {len(columns)} 列，用 `wren_query(\"SELECT * FROM {model['name']} LIMIT 5\")` 查看全部）"
        lines.append(f"  列: {shown}")
    if len(layer.models) > _MAX_MODELS_IN_PROMPT:
        lines.append(f"- …（共 {len(layer.models)} 个模型，其余省略）")

    # 表间关系（同名列自动推断）：多表 JOIN 时直接可用，省去逐轮试探
    if layer.relationships:
        lines += [
            "",
            "## 表间关系（自动推断）",
            "以下 JOIN 关系由跨表同名键列推断，业务上不一定成立；使用前可 `wren_dry_run` 验证，明显不合理时以数据为准：",
        ]
        for rel in layer.relationships[:_MAX_RELATIONSHIPS_IN_PROMPT]:
            lines.append(f"- {rel['condition']}")
        if len(layer.relationships) > _MAX_RELATIONSHIPS_IN_PROMPT:
            lines.append(f"- …（共 {len(layer.relationships)} 条，其余省略）")

    # 指引只针对本轮实际展示的模型（省略部分模型不参与编目判断）
    uncataloged = len(shown_models) - cataloged_tables
    if uncataloged > 0:
        lines += [
            "",
            "## 数据编目（本轮优先做，与任务相关的表）",
            "以上部分表还没有列含义登记。在开始分析前，先对**与任务相关的表**编目：",
            "1. 采样查看数据（如 `wren_query(\"SELECT * FROM 表名 LIMIT 5\")`，枚举列可加 `GROUP BY`）",
            "2. 推断每列的业务含义（单位、口径、枚举值语义，如“status=A 表示什么”）",
            "3. 调用 `wren_describe(\"表名\", {\"列名\": \"含义\", ...})` 登记 —— 登记后本轮及后续所有分析自动使用，无需重复推断",
            "4. **对影响分析结论且无法从数据本身推断的歧义**（单位不明、口径有二义、枚举值语义不明），不要臆测：在给用户的回复中明确列出这些问题请其确认，得到答复后再登记或使用",
            "编目完成后继续执行分析任务。",
        ]
    return "\n".join(lines)


def _extract_code_to_execute(code_content: str) -> str | None:
    if not code_content:
        return None
    # Prefer a fenced block whose opening line carries an optional single-token
    # info string (```python / ```py / ```Python3 ...); fall back to the legacy
    # inline form so bare ``` ... ``` fences keep working.
    md_match = _FENCE_WITH_INFO_RE.search(code_content) or _FENCE_INLINE_RE.search(
        code_content
    )
    code_str = md_match.group(1).strip() if md_match else code_content
    bootstraps: list[str] = []
    if re.search(r"\bwren_(?:query|dry_run|describe|remember)\s*\(", code_str):
        bootstraps.append(WREN_QUERY_BOOTSTRAP)
    if re.search(r"(^|\W)(plt\.|matplotlib|sns\.|seaborn)", code_str, re.IGNORECASE):
        bootstraps.append(CHINESE_MATPLOTLIB_BOOTSTRAP)
    if bootstraps:
        return "\n".join(bootstraps) + "\n" + code_str
    return code_str


def _salvage_protocol_output(content: str) -> str:
    """Protocol-parse failure fallback: rebuild action blocks with naive regex.

    Non-native models (custom provider, e.g. MiniMax) often emit leading free
    text before the first action tag, or emit unpaired backticks / code fences
    that make mask_backticked_content hide the real tags and break the strict
    parser. This salvage rebuilds the output without relying on backtick
    masking: the last complete <Code>/<Answer> block becomes the terminal
    action, its fence markers are balanced, and the remaining prose (action
    tags stripped, stray backticks neutralized) is folded into an <Analyze>
    prefix so the code stays executable.
    """
    raw = content or ""
    tag_strip_re = r"</?(?:Analyze|Understand|Code|Answer|Execute|File)>"
    fence_re = re.compile(r"```", re.IGNORECASE)

    def balance_fences(text: str) -> str:
        if len(fence_re.findall(text)) % 2 == 1:
            return text.rstrip() + "\n```"
        return text

    def wrap_plain(text: str) -> str:
        cleaned = re.sub(tag_strip_re, "\n", text).strip()
        if not cleaned:
            return raw
        if re.search(r"```(?:python|py|python3)?\s*\r?\n", cleaned, re.IGNORECASE):
            return f"<Code>\n{balance_fences(cleaned)}\n</Code>"
        return f"<Answer>\n{cleaned.replace('`', chr(39))}\n</Answer>"

    terminal_match = None
    terminal_tag = None
    for tag in ("Code", "Answer"):
        for match in re.finditer(rf"<{tag}>(.*?)</{tag}>", raw, re.DOTALL):
            if terminal_match is None or match.start() >= terminal_match.start():
                terminal_match, terminal_tag = match, tag
    if terminal_match is None:
        return wrap_plain(raw)

    body = terminal_match.group(1).strip()
    if not body:
        return wrap_plain(raw)

    # Neutralize nested action tags inside the terminal body: non-native
    # models (e.g. MiniMax) sometimes emit <Understand>/<Analyze> prose inside
    # <Code>, which trips the strict parser's nesting check on re-validation.
    body = re.sub(tag_strip_re, "\n", body).strip()
    if not body:
        return wrap_plain(raw)

    if terminal_tag == "Code":
        body = balance_fences(body)
    else:
        body = body.replace("`", chr(39))

    prefix_raw = raw[: terminal_match.start()]
    prefix_text = re.sub(tag_strip_re, "\n", prefix_raw).strip().replace("`", chr(39))
    parts: list[str] = []
    if prefix_text:
        parts.append(f"<Analyze>\n{prefix_text}\n</Analyze>")
    parts.append(f"<{terminal_tag}>\n{body}\n</{terminal_tag}>")
    return "\n".join(parts)


def _save_answer_markdown_report(
    answer_content: str,
    workspace_dir: str,
    session_id: str,
) -> Path | None:
    if not answer_content:
        return None

    workspace_root = Path(workspace_dir).resolve()
    generated_root = (workspace_root / "generated").resolve()
    generated_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = uniquify_path(generated_root / f"Answer_Report_{timestamp}.md")
    report_path.write_text(answer_content.rstrip() + "\n", encoding="utf-8")

    rel_path = report_path.relative_to(workspace_root).as_posix()
    register_generated_paths(session_id, [rel_path])
    return report_path


def _prewarm_execution_backend(
    session_id: str,
    stop_event: threading.Event,
) -> None:
    """Allocate/reuse the session container while the model is still generating,
    so the first <Code> block does not pay the container start-up cost."""
    if stop_event.is_set():
        return
    try:
        ensure_execution_backend_ready(session_id)
        if stop_event.is_set():
            release_session_container(session_id)
    except Exception as exc:  # pragma: no cover - best-effort warm-up
        logger.warning("container prewarm failed for %s: %s", session_id, exc)


def bot_stream(
    messages: list[dict[str, Any]],
    workspace: list[str] | None,
    session_id: str = "default",
    runtime_config: ChatRuntimeConfig | None = None,
    *,
    interaction_mode: str = "auto",
    resume_state: dict[str, Any] | None = None,
    additional_instruction: str = "",
    max_rounds: int | None = None,
    max_duration_sec: int | None = None,
):
    runtime_config = runtime_config or ChatRuntimeConfig()
    # 前端可按请求覆盖预算（chat_max_rounds / chat_max_duration_sec），非法值回退全局配置
    rounds_budget = (
        max_rounds if isinstance(max_rounds, int) and max_rounds > 0 else settings.chat_max_rounds
    )
    duration_budget = (
        max_duration_sec
        if isinstance(max_duration_sec, int) and max_duration_sec > 0
        else settings.chat_max_duration_sec
    )
    interaction_mode = "manual" if interaction_mode == "manual" else "auto"
    session_id = validate_session_id(session_id)
    session_lock = try_acquire_session_run(session_id)
    if session_lock is None:
        yield _execution_status_block("Session Busy", "another analysis is already running")
        return

    stop_event = begin_session_run_stop_event(session_id)
    try:
        workspace_paths = list(workspace or [])
        workspace_dir = get_session_workspace(session_id)
        Path(workspace_dir, "generated").mkdir(parents=True, exist_ok=True)
        if settings.use_docker_execution:
            threading.Thread(
                target=_prewarm_execution_backend,
                args=(session_id, stop_event),
                daemon=True,
            ).start()
        if resume_state is not None:
            conversation = deepcopy(resume_state.get("conversation") or [])
            if not conversation:
                yield _execution_status_block(
                    "Continuation Error",
                    "the paused analysis context is unavailable",
                )
                return
            execution_feedback = _append_additional_instruction(
                str(resume_state.get("execution_output") or ""),
                additional_instruction,
            )
            conversation.append(
                _build_execution_feedback_message(runtime_config, execution_feedback)
            )
            is_initial_conversation = False
            round_count = max(0, int(resume_state.get("round_count") or 0))
            code_execution_count = max(
                0,
                int(resume_state.get("code_execution_count") or 0),
            )
            elapsed_seconds = max(
                0.0,
                float(resume_state.get("elapsed_seconds") or 0.0),
            )
            started_at = time.monotonic() - min(
                elapsed_seconds,
                float(duration_budget),
            )
            clear_pending_continuation(session_id)
            logger.info(
                "manual_analysis_resumed session_id=%s additional_instruction=%s mode=%s",
                session_id,
                bool(str(additional_instruction or "").strip()),
                interaction_mode,
            )
        else:
            conversation = deepcopy(messages or [])
            is_initial_conversation = not any(
                message.get("role") == "assistant" for message in conversation
            )
            if conversation and conversation[0].get("role") == "assistant":
                conversation = conversation[1:]

            _build_user_prompt(
                conversation,
                workspace_paths,
                workspace_dir,
                use_all_files_when_empty=workspace is None,
                session_id=session_id,
            )
            round_count = 0
            code_execution_count = 0
            started_at = time.monotonic()
        initial_workspace = {
            path.resolve() for path in Path(workspace_dir).rglob("*") if path.is_file()
        }
        finished = False
        while not finished:
            if stop_event.is_set():
                break
            if time.monotonic() - started_at >= duration_budget:
                yield _execution_status_block(
                    "Budget Exceeded",
                    f"analysis exceeded {duration_budget} seconds",
                )
                break
            if round_count >= rounds_budget:
                yield _execution_status_block(
                    "Budget Exceeded",
                    f"analysis exceeded {rounds_budget} model rounds",
                )
                break
            round_count += 1
            logger.warning(
                "analysis_round_start session_id=%s round=%d", session_id, round_count
            )

            cur_res = ""
            initial_stream_state = _InitialStreamState()
            stream_iter = (
                _iter_heywhale_stream(
                    conversation,
                    runtime_config,
                    session_id,
                    stop_event,
                )
                if runtime_config.provider == "heywhale"
                else (
                    _iter_custom_stream(
                        conversation,
                        runtime_config,
                        session_id,
                        stop_event,
                    )
                    if runtime_config.provider == "custom"
                    else _iter_local_stream(
                        conversation,
                        runtime_config,
                        session_id,
                        stop_event,
                    )
                )
            )
            try:
                stream_model_output = None
                pending_model_deltas: list[str] = []
                for delta, chunk in _iter_stream_with_cancellation(
                    stream_iter,
                    stop_event,
                    session_id,
                ):
                    if stop_event.is_set():
                        break
                    if time.monotonic() - started_at >= duration_budget:
                        yield _execution_status_block(
                            "Budget Exceeded",
                            f"analysis exceeded {duration_budget} seconds",
                        )
                        finished = True
                        break
                    if delta is not None:
                        cur_res += delta
                        if len(cur_res) > settings.chat_max_response_chars:
                            yield _execution_status_block(
                                "Budget Exceeded",
                                "model response exceeded the configured size limit",
                            )
                            finished = True
                            break
                        if stream_model_output is None:
                            pending_model_deltas.append(delta)
                            leading = cur_res.lstrip()
                            if not leading:
                                continue
                            if leading.startswith("<") and ">" not in leading:
                                continue
                            stream_model_output = bool(
                                _MODEL_ACTION_TAG_AT_START_RE.match(leading)
                                or (is_initial_conversation and round_count == 1)
                            )
                        if stream_model_output:
                            if pending_model_deltas:
                                if is_initial_conversation and round_count == 1:
                                    prepared_deltas = _prepare_initial_stream_deltas(
                                        pending_model_deltas,
                                        initial_stream_state,
                                    )
                                    for prepared_delta in prepared_deltas:
                                        yield prepared_delta
                                else:
                                    yield from pending_model_deltas
                                pending_model_deltas.clear()
                            else:
                                if is_initial_conversation and round_count == 1:
                                    yield from _format_initial_stream_delta(
                                        delta,
                                        initial_stream_state,
                                    )
                                else:
                                    yield delta
                    if find_completed_action_end(cur_res) is not None:
                        break
            except (httpx.HTTPError, openai.OpenAIError) as exc:
                if stop_event.is_set():
                    break
                yield _execution_status_block("Model Error", str(exc))
                return

            if stop_event.is_set() or finished:
                break

            if (
                is_initial_conversation
                and round_count == 1
                and initial_stream_state.synthetic_analyze_open
            ):
                yield "</Analyze>"
                initial_stream_state.synthetic_analyze_open = False

            if is_initial_conversation and round_count == 1:
                cur_res = _prefix_initial_analyze_tag(cur_res)

            try:
                normalized_res, actions = normalize_model_output(cur_res)
            except ProtocolValidationError as exc:
                # Fallback for non-native models (e.g. MiniMax via custom
                # provider): leading free text / unpaired backticks can defeat
                # the masking-based parser. Rebuild with naive regex first,
                # then retry with backticks stripped; only then give up.
                salvaged = False
                first_candidate = _salvage_protocol_output(cur_res)
                for candidate in (
                    first_candidate,
                    first_candidate.replace("`", "'"),
                ):
                    try:
                        normalized_res, actions = normalize_model_output(candidate)
                    except ProtocolValidationError:
                        continue
                    cur_res = candidate
                    salvaged = True
                    logger.info(
                        "salvaged non-compliant model output for session %s",
                        session_id,
                    )
                    break
                if not salvaged:
                    yield _execution_status_block("Protocol Error", str(exc))
                    break
            if normalized_res != cur_res.strip():
                logger.info("normalized model action format for session %s", session_id)
            if not stream_model_output:
                # 普通文本或格式漂移响应需要先规范化后展示；符合协议的标签响应已在上面逐增量转发。
                yield normalized_res
            cur_res = normalized_res

            terminal_action = actions[-1]
            if terminal_action.tag == "Answer":
                report_path = _save_answer_markdown_report(
                    terminal_action.body,
                    workspace_dir,
                    session_id,
                )
                if report_path is not None:
                    file_block = build_file_block([report_path], workspace_dir, session_id)
                    if file_block:
                        yield file_block
                finished = True
                continue

            # 语义层咨询：模型用 <ConsultWren> 提问时返回 session 数据模型清单
            if terminal_action.tag == "ConsultWren":
                conversation.append({"role": "assistant", "content": cur_res})
                layer = ensure_semantic_layer(session_id)
                reply = (
                    _build_session_semantic_context(layer)
                    if layer is not None
                    else "当前 session 无上传数据语义层。请直接用 pandas 读取工作区文件。"
                )
                reply_block = f"\n<WrenReply>\n{reply}\n</WrenReply>\n"
                yield reply_block
                conversation.append(
                    _build_execution_feedback_message(runtime_config, reply)
                )
                if stop_event.is_set():
                    break
                continue

            code_execution_count += 1
            conversation.append({"role": "assistant", "content": cur_res})
            code_str = _extract_code_to_execute(terminal_action.body)
            if not code_str:
                yield _execution_status_block("Protocol Error", "empty executable code")
                break

            remaining_seconds = max(
                1,
                duration_budget - int(time.monotonic() - started_at),
            )
            outcome = execute_managed_code(
                code_str,
                session_id,
                source="agent",
                timeout_sec=min(settings.execution_timeout_sec, remaining_seconds),
                cancel_event=stop_event,
            )
            if interaction_mode == "manual":
                save_pending_continuation(
                    session_id,
                    {
                        "conversation": conversation,
                        "execution_output": outcome.result,
                        "round_count": round_count,
                        "code_execution_count": code_execution_count,
                        "elapsed_seconds": time.monotonic() - started_at,
                    },
                )
                logger.info(
                    "manual_analysis_paused session_id=%s round=%s executions=%s",
                    session_id,
                    round_count,
                    code_execution_count,
                )
            yield outcome.execution_content
            # 观测点：本轮代码是否调用 wren_remember()（仅匹配实参调用，不含 def 行）
            remember_calls = re.findall(r"(?m)^\s*wren_remember\s*\(", code_str)
            if remember_calls:
                logger.info(
                    "memory.registered session_id=%s round=%s count=%s",
                    session_id,
                    round_count,
                    len(remember_calls),
                )
            else:
                # 让"模型未调用"也变成可观测信号：info 级，单行便于 grep
                logger.info(
                    "memory.skipped session_id=%s round=%s reason=no_wren_remember_call",
                    session_id,
                    round_count,
                )

            if interaction_mode == "manual":
                return

            conversation.append(
                _build_execution_feedback_message(
                    runtime_config,
                    _truncate_execution_output_for_context(outcome.result),
                )
            )
            # 长对话压缩：总量超预算时折叠最旧代码轮次（就地修改，最近轮保留原文）
            _compact_conversation(conversation)
            if stop_event.is_set():
                yield _execution_status_block(
                    "Stopped", "analysis was stopped after code execution"
                )
                break

            current_files = {
                path.resolve() for path in Path(workspace_dir).rglob("*") if path.is_file()
            }
            new_files = [str(path) for path in current_files - initial_workspace]
            if new_files:
                workspace_paths.extend(new_files)
                initial_workspace.update(Path(path).resolve() for path in new_files)
    except GeneratorExit:
        # The client disconnected mid-stream; make sure the analysis loop and any
        # queued sandbox execution stop instead of burning the remaining budget.
        stop_event.set()
        raise
    finally:
        release_session_run(session_id, session_lock)
