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
from ..settings import CHINESE_MATPLOTLIB_BOOTSTRAP, WREN_QUERY_BOOTSTRAP, settings


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
    r"^<(?:Analyze|Understand|Code|Answer)>",
)
_MODEL_ACTION_TAG_RE = re.compile(r"<(?:Analyze|Understand|Code|Answer)>")
_MODEL_ACTION_CLOSE_TAG_RE = re.compile(r"</(?:Analyze|Understand|Code|Answer)>")
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
    if re.search(r"\bwren_query\s*\(", code_str):
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
):
    runtime_config = runtime_config or ChatRuntimeConfig()
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
                float(settings.chat_max_duration_sec),
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
            if time.monotonic() - started_at >= settings.chat_max_duration_sec:
                yield _execution_status_block(
                    "Budget Exceeded",
                    f"analysis exceeded {settings.chat_max_duration_sec} seconds",
                )
                break
            if round_count >= settings.chat_max_rounds:
                yield _execution_status_block(
                    "Budget Exceeded",
                    f"analysis exceeded {settings.chat_max_rounds} model rounds",
                )
                break
            round_count += 1

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
                    if time.monotonic() - started_at >= settings.chat_max_duration_sec:
                        yield _execution_status_block(
                            "Budget Exceeded",
                            f"analysis exceeded {settings.chat_max_duration_sec} seconds",
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

            code_execution_count += 1
            conversation.append({"role": "assistant", "content": cur_res})
            code_str = _extract_code_to_execute(terminal_action.body)
            if not code_str:
                yield _execution_status_block("Protocol Error", "empty executable code")
                break

            remaining_seconds = max(
                1,
                settings.chat_max_duration_sec - int(time.monotonic() - started_at),
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

            if interaction_mode == "manual":
                return

            conversation.append(
                _build_execution_feedback_message(runtime_config, outcome.result)
            )
            if stop_event.is_set():
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
