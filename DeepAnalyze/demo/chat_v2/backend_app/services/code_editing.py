from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chat import ChatRuntimeConfig


CODE_EDIT_SYSTEM_PROMPT = """You are a careful code editing assistant.

You will receive one Python script and one natural-language edit instruction.
Return the complete modified Python script only inside <ModifiedCode>...</ModifiedCode>.
Do not include explanations, markdown fences, diff markers, or partial snippets.
Preserve unrelated code exactly where possible.
"""


@dataclass(frozen=True)
class CodeEditResult:
    code: str
    raw_response: str


def build_code_edit_messages(code: str, instruction: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CODE_EDIT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "# Current Python Script\n"
                "```python\n"
                f"{code.rstrip()}\n"
                "```\n\n"
                "# Edit Instruction\n"
                f"{instruction.strip()}\n"
            ),
        },
    ]


def extract_modified_code(response: str) -> str:
    raw = response or ""
    if not raw.strip():
        raise ValueError("LLM response is empty")

    tag_match = re.search(
        r"<ModifiedCode>\s*(.*?)\s*</ModifiedCode>",
        raw,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if tag_match:
        return _strip_code_fence(tag_match.group(1))

    code_block_match = re.search(
        r"```(?:python|py)?\s*\n(.*?)```",
        raw,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if code_block_match:
        return _strip_code_fence(code_block_match.group(1))

    stripped = raw.strip()
    if not _looks_like_code(stripped):
        raise ValueError("LLM response does not contain modified code")
    return stripped


def edit_code_with_llm(
    code: str,
    instruction: str,
    runtime_config: "ChatRuntimeConfig",
) -> CodeEditResult:
    if not code.strip():
        raise ValueError("Code is required")
    if not instruction.strip():
        raise ValueError("Instruction is required")

    conversation = build_code_edit_messages(code, instruction)
    raw_response = "".join(_iter_completion_text(conversation, runtime_config))
    return CodeEditResult(
        code=extract_modified_code(raw_response),
        raw_response=raw_response,
    )


def _iter_completion_text(
    conversation: list[dict[str, str]],
    runtime_config: "ChatRuntimeConfig",
) -> Iterable[str]:
    import httpx

    from .chat import _iter_custom_stream, _iter_heywhale_stream, _iter_local_stream

    stream_iter = (
        _iter_heywhale_stream(conversation, runtime_config)
        if runtime_config.provider == "heywhale"
        else (
            _iter_custom_stream(conversation, runtime_config)
            if runtime_config.provider == "custom"
            else _iter_local_stream(conversation, runtime_config)
        )
    )
    try:
        for delta, _chunk in stream_iter:
            if delta:
                yield delta
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Code edit LLM request failed: {exc}") from exc


def _strip_code_fence(content: str) -> str:
    text = (content or "").strip()
    nested_match = re.fullmatch(
        r"```(?:python|py)?\s*\n(.*?)```",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if nested_match:
        text = nested_match.group(1)
    return text.strip()


def _looks_like_code(content: str) -> bool:
    code_markers = (
        "\n",
        "import ",
        "from ",
        "def ",
        "class ",
        "print(",
        "=",
        "for ",
        "while ",
        "if ",
    )
    return any(marker in content for marker in code_markers)
