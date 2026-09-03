from __future__ import annotations

import difflib
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .execution import (
    build_file_block,
    collect_artifact_paths,
    execute_code_safe,
    snapshot_workspace_files,
)
from .session_state import append_execution_record
from .workspace import (
    build_download_url,
    get_session_workspace,
    register_generated_paths,
)
from ..settings import settings


@dataclass(frozen=True)
class ExecutionOutcome:
    run_id: str
    success: bool
    result: str
    source: str
    script_path: str
    instruction: str
    diff: str
    artifacts: list[dict[str, object]]
    started_at: str
    finished_at: str
    execution_content: str
    trace_content: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_diff(original_code: str, code: str) -> str:
    if not original_code or original_code == code:
        return ""
    return "\n".join(
        difflib.unified_diff(
            original_code.splitlines(),
            code.splitlines(),
            fromfile="before.py",
            tofile="after.py",
            lineterm="",
        )
    )


def _truncate_output(text: str, limit: int) -> str:
    """Keep execution output bounded before it is streamed to the UI and
    re-injected into the model context (a runaway print loop would otherwise
    blow up both)."""
    if limit <= 0 or len(text) <= limit:
        return text
    head = text[: limit // 2].rstrip()
    tail = text[-(limit - limit // 2) :].lstrip()
    omitted = len(text) - len(head) - len(tail)
    return (
        f"{head}\n\n... [output truncated: {omitted} characters omitted] ...\n\n{tail}"
    )


def execute_managed_code(
    code: str,
    session_id: str,
    *,
    source: str,
    instruction: str = "",
    original_code: str = "",
    timeout_sec: int | None = None,
    cancel_event: threading.Event | None = None,
) -> ExecutionOutcome:
    if not code.strip():
        raise ValueError("Code is required")

    workspace_root = Path(get_session_workspace(session_id)).resolve()
    generated_root = workspace_root / "generated"
    code_root = generated_root / "code"
    code_root.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    started_at = _utc_now()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_source = "agent" if source == "agent" else "manual"
    script_path = code_root / f"{timestamp}_{safe_source}_{run_id[:8]}.py"

    before_state = snapshot_workspace_files(str(workspace_root))
    script_path.write_text(code.rstrip() + "\n", encoding="utf-8")
    result = execute_code_safe(
        code,
        str(workspace_root),
        session_id,
        timeout_sec,
        cancel_event,
    )
    result = _truncate_output(result, settings.execution_output_max_chars)
    after_state = snapshot_workspace_files(str(workspace_root))
    artifact_paths = collect_artifact_paths(
        before_state,
        after_state,
        str(generated_root),
        session_id,
    )
    script_relative = script_path.relative_to(workspace_root).as_posix()
    register_generated_paths(session_id, [script_relative])
    if script_path.resolve() not in {path.resolve() for path in artifact_paths}:
        artifact_paths.insert(0, script_path.resolve())

    artifacts = []
    for path in artifact_paths:
        try:
            relative = path.resolve().relative_to(workspace_root).as_posix()
        except ValueError:
            continue
        artifacts.append(
            {
                "name": path.name,
                "path": relative,
                "size": path.stat().st_size,
                "download_url": build_download_url(f"{session_id}/{relative}"),
            }
        )

    execution_block = f"\n<Execute>\n```\n{result}\n```\n</Execute>\n"
    file_block = build_file_block(artifact_paths, str(workspace_root), session_id)
    execution_content = execution_block + file_block
    code_block = f"<Code>\n```python\n{code.rstrip()}\n```\n</Code>\n"
    finished_at = _utc_now()
    success = not result.startswith(("[Error]", "[Timeout]", "[Cancelled]"))
    outcome = ExecutionOutcome(
        run_id=run_id,
        success=success,
        result=result,
        source=safe_source,
        script_path=script_relative,
        instruction=instruction.strip(),
        diff=_build_diff(original_code, code),
        artifacts=artifacts,
        started_at=started_at,
        finished_at=finished_at,
        execution_content=execution_content,
        trace_content=code_block + execution_content,
    )
    append_execution_record(session_id, outcome.to_dict())
    return outcome
