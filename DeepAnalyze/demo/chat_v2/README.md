# DA-Studio (Chat Demo)

`demo/chat_v2` is **DA-Studio**, the browser-based DeepAnalyze demo system presented in the PVLDB demo paper *"DA-Studio: An Agentic System for End-to-End Data Analysis"*. It includes the backend API, the workspace/file layer, the frontend UI, and both local and Docker execution modes.

[Chinese Version](./README_ZH.md)

## Features

- Upload and manage tables, databases, text files, logs, and documents in the workspace
- Preview common workspace files directly in the UI
- Stream structured `<Analyze> / <Understand> / <Code> / <Execute> / <File> / <Answer>` blocks
- Execute Python analysis code inside the workspace
- Export Markdown and PDF reports
- Switch between Chinese and English UI
- Run code either locally or inside Docker
- Choose model provider: Local, HeyWhale API, or Custom OpenAI-compatible API
- Select the exact workspace files included in each analysis task
- Restore task configuration, chat traces, and execution history per session
- Persist every agent/manual code run with its script, diff, output, and artifacts

## Model Provider Settings

In the left configuration panel:

- `Local`: uses your local DeepAnalyze-compatible endpoint.
- `HeyWhale API`: requires `API Key`; API base uses the built-in HeyWhale endpoint by default.
- `Custom Model`: requires your own `Model Name` and `API Base`; `API Key` is optional.

When provider is `Custom Model`, the frontend automatically prepends a structured data-analysis system prefix:

- English UI => English prefix
- Chinese UI => Chinese prefix

For local or HeyWhale DeepAnalyze usage, this extra prefix is not injected.

## Prerequisites

### 1. Model service

Start a DeepAnalyze model service first, for example:

```bash
vllm serve DeepAnalyze-8B
```

By default the chat demo connects to an OpenAI-compatible endpoint around `http://localhost:8000`.

### 2. Python and Node.js

Recommended setup:

- Python: use your existing DeepAnalyze environment, for example `deepanalyze`
- Node.js: use a version that can run the bundled Next.js frontend

Install frontend dependencies once:

```bash
cd demo/chat_v2/frontend
npm install
cd ..
```

### 3. Environment variables

Use the sample config file:

```bash
cd demo/chat_v2
cp .env.example .env
```

Windows:

```powershell
cd demo/chat_v2
Copy-Item .env.example .env
```

## Execution Modes

### Local mode

Local execution is intended only for trusted development environments. It runs generated
Python directly on the host and is disabled unless the risk is explicitly accepted:

```env
DEEPANALYZE_EXECUTION_MODE=local
DEEPANALYZE_ALLOW_UNSAFE_LOCAL_EXECUTION=true
```

### Docker mode

Docker is the default and required mode for sandboxed execution. Each session receives a
separate container that mounts only that session's workspace. Network access is disabled
by default, and memory, CPU, PID, read-only filesystem, non-root user, and execution-time
limits are applied from `.env`.

```env
DEEPANALYZE_EXECUTION_MODE=docker
```

At startup, the backend checks both the Docker CLI and daemon. If the execution
image is missing, it is built automatically from the bundled `Dockerfile.exec`.
The first startup takes longer because it downloads the base image and Python
dependencies.

Disable automatic builds when images are managed by an external deployment pipeline:

```env
DEEPANALYZE_DOCKER_AUTO_BUILD=false
```

The image can also be built manually:

Example:

```bash
cd demo/chat_v2
docker build -t deepanalyze-chat-exec:latest -f Dockerfile.exec .
```

Resource limits can be adjusted with `DEEPANALYZE_DOCKER_MEMORY`, `DEEPANALYZE_DOCKER_CPUS`,
`DEEPANALYZE_DOCKER_PIDS_LIMIT`, and `DEEPANALYZE_DOCKER_NETWORK_MODE`.

## Safety And Agent Budgets

- Session identifiers and all workspace paths are validated against the workspace root.
- Uploads are streamed and constrained by per-file, per-session size, and file-count limits.
- Model output must contain complete structured actions and exactly one terminal
  `<Code>` or `<Answer>` block. Incomplete code is never executed.
- Each session permits only one active analysis or manual execution.
- Agent rounds, response size, total duration, and individual code runs
  have independent limits. `/chat/stop` also cancels an active code execution.

## Session State And Managed Execution

Session state is stored under `.session_state/<session>/session.json` beside, not inside,
the execution workspaces. It is never mounted into sandbox containers or exposed by
workspace APIs, and it survives clearing user workspace files. The browser restores this
server state first and uses a session-scoped local cache only as an offline fallback.

Both autonomous `<Code>` actions and Code Lab reruns use the same managed execution service.
Each run saves a versioned script under `generated/code/`, registers changed artifacts,
records the edit instruction and unified diff, and emits a Code/Execute/File trace that is
included in later report exports.

The chat composer defaults to **Auto** interaction mode. In **Manual** mode, the backend
pauses after every code execution: the Execute block is already visible in the browser, but
its result has not yet been sent to the model. Continue directly or enter an optional
instruction before continuing. The backend appends a non-empty instruction to the pending
execution feedback with this stable format:

```text
<execution output>

# Additional Instruction
<user instruction>
```

The pending continuation is stored in the server-side session state, so the waiting state
survives a browser refresh without exposing the internal model conversation through the
session API.

## Run

The single canonical entry point is `D:\DataAI\start-all.ps1` (Windows) or the
equivalent shell invocation on Linux/macOS. There are no per-project start/stop
scripts in `demo/chat_v2/`.

### Windows

```powershell
# From the repo root (D:\DataAI):
powershell -ExecutionPolicy Bypass -File start-all.ps1
```

Stop:

```powershell
powershell -ExecutionPolicy Bypass -File stop-all.ps1
```

Default addresses after startup:

- Frontend: `http://localhost:4000`
- Backend API: `http://localhost:9000`
- File service: `http://localhost:8100`

Ports can be changed in `.env`. The startup and stop scripts use these values,
and the startup script automatically points the frontend at the configured backend:

```env
DEEPANALYZE_BACKEND_PORT=8300
DEEPANALYZE_FILE_SERVER_PORT=8100
FRONTEND_PORT=4000
```

## PDF Export

PDF export depends on:

- `pypandoc`
- `pandoc`
- `xelatex`

Behavior details:

- If `pandoc` is missing, the backend will try to auto-download it (enabled by default).
- `xelatex` is still required and must be installed manually.
- You can control this with:
  - `DEEPANALYZE_PDF_AUTO_DOWNLOAD_PANDOC` (`true` by default)
  - `DEEPANALYZE_PDF_PANDOC_CACHE_DIR` (optional pandoc cache path)

## Directory Overview

- `backend.py`: backend startup entry
- `backend_app/`: FastAPI backend implementation
- `frontend/`: Next.js frontend
- `Dockerfile.exec`: Docker image for code execution
- `workspace/`: per-session workspace
- `logs/`: runtime logs
