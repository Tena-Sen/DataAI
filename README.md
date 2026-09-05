<div align="center">

# DataAI

**A local, governed workspace for conversational data analysis**

[English](README.md) · [简体中文](README_ZH.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-Frontend-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![DuckDB](https://img.shields.io/badge/DuckDB-Analytics-FFF000?logo=duckdb&logoColor=black)](https://duckdb.org/)

</div>

DataAI combines [DeepAnalyze](https://github.com/ruc-datalab/DeepAnalyze) and [WrenAI](https://github.com/Canner/WrenAI) into a local conversational analytics workspace. Ask questions in natural language, query uploaded data, generate and execute analysis code, create visualizations, and export reports—all with isolated user sessions and governed semantic queries.

> **From a natural-language question to a reproducible analysis.**

## Why DataAI?

DataAI connects autonomous data science with a governed semantic layer. Instead of switching between a database client, a notebook, a charting tool, and a report editor, users can move through the complete workflow from one conversational workspace.

| Capability | What it provides |
| --- | --- |
| Natural-language analysis | Describe an analytical goal and let the agent plan the next steps. |
| Governed text-to-SQL | Query uploaded data through WrenAI’s semantic layer and dynamic MDL. |
| Reproducible execution | Generate and run Python analysis code in a Docker sandbox or local mode. |
| Workspace isolation | Keep accounts, sessions, uploaded data, model settings, and outputs separated by user. |
| Analysis deliverables | Preview and download generated charts, tables, and reports from the session workspace. |

## Architecture

```text
┌────────────────────────────────────────────────────────────┐
│  Browser · http://localhost:4000                           │
│  Next.js UI · authentication · chat · workspace files      │
└──────────────────────────┬─────────────────────────────────┘
                           │ same-origin /api proxy + auth cookie
┌──────────────────────────▼─────────────────────────────────┐
│  DeepAnalyze backend · http://localhost:9000               │
│  FastAPI · auth · sessions · code execution · exports      │
│  └─ starts the WrenAI query service on demand              │
└───────────────┬──────────────────────────┬────────────────┘
                │ OpenAI-compatible API     │ wren_query() bridge
┌───────────────▼──────────────┐  ┌────────▼─────────────────┐
│ LLM inference service         │  │ WrenAI environment        │
│ vLLM :8000 or custom API     │  │ semantic layer · MDL      │
└──────────────────────────────┘  └────────┬─────────────────┘
                                           │ DuckDB
                                  ┌────────▼─────────┐
                                  │ Session data      │
                                  │ CSV · Excel       │
                                  │ SQLite · DuckDB   │
                                  └───────────────────┘
```

WrenAI is not run as a separate permanent HTTP or MCP application. When the backend starts, it can launch an on-demand query service at `127.0.0.1:9471` to avoid the overhead of starting `wren.exe query` for every request. If the service is unavailable, the execution layer falls back to a CLI subprocess. In Docker mode, network isolation means the execution layer always uses the CLI fallback.

## Quick Start

### Prerequisites

- Windows with PowerShell; the included start and stop scripts use PowerShell.
- Python virtual environments for `DeepAnalyze` and `WrenAI`.
- Node.js and npm or pnpm.
- A local vLLM server, or any OpenAI-compatible API. The default endpoint is `http://localhost:8000/v1`.

### 1. Prepare the environments

```powershell
# DeepAnalyze backend
python -m venv DeepAnalyze\.venv
DeepAnalyze\.venv\Scripts\pip install -r DeepAnalyze\requirements.txt

# WrenAI and the Wren CLI
cd WrenAI
python -m venv .venv
.\.venv\Scripts\pip install -e ".\core\wren-core-base" -e ".\core\wren-core-py" -e ".\core\wren"
cd ..
```

The backend defaults to `D:\DataAI\WrenAI\.venv\Scripts\wren.exe`. If your path differs, copy `DeepAnalyze/demo/chat_v2/.env.example` to `.env` and update `DEEPANALYZE_WREN_CLI`.

### 2. Start DataAI

```powershell
powershell -ExecutionPolicy Bypass -File start-all.ps1
```

| Service | Address | Role |
| --- | --- | --- |
| DeepAnalyze backend | <http://localhost:9000> | API, sessions, execution, and exports |
| DataAI frontend | <http://localhost:4000> | Login, chat, and workspace UI |
| WrenAI query service | `127.0.0.1:9471` | Started on demand by the backend |

Open <http://localhost:4000> in your browser.

### 3. Stop DataAI

```powershell
powershell -ExecutionPolicy Bypass -File stop-all.ps1
```

This stops the processes associated with ports `9000`, `4000`, and `9471`.

## Core Features

### Authentication and session isolation

- Register an account on first use. Usernames support lowercase letters, numbers, underscores, and hyphens; valid length is 3–32 characters.
- Sessions are stored on the server under the current user and can be restored after signing in again.
- Cross-user access is rejected with `403`.
- The first registered user can claim historical sessions that do not yet have an owner.
- The user menu provides session history, session switching, new sessions, and sign-out.

### Per-user model settings

- Choose a local vLLM endpoint, the HeyWhale API, or another OpenAI-compatible custom endpoint.
- Save settings on the server and restore them automatically across browsers and devices.
- Test a connection with a real model request and inspect latency or the failure reason.
- Settings are isolated by username.

### Data analysis workflow

- Upload CSV, Excel, or SQLite files, or load one of the four built-in example datasets.
- Describe an analytical task in natural language. The agent generates and executes Python code in a Docker sandbox by default, with an optional local mode.
- Store generated charts, tables, and reports in the session’s `generated/` directory for preview and download.
- Use `wren_query()` and `wren_dry_run()` for semantic-layer queries, `wren_describe()` to register column meanings, and `wren_remember()` to reuse successful natural-language-to-SQL queries across sessions.
- Compress long context automatically to stay within the model context window.

### WrenAI semantic layer

- On the first upload in a session, CSV and Excel files are imported into DuckDB and a dynamic MDL is generated.
- The per-session engine lives at `workspace/<session>/.deepanalyze/wren/` and contains `mdl.json`, `conn.json`, and the DuckDB database.
- Original table and column names are retained after normalization to valid identifiers; Chinese names are preserved.
- Subsequent queries use the resident service at `127.0.0.1:9471` when available and fall back to the CLI when necessary.

## Repository Layout

```text
DataAI/
├── README.md                         # English documentation
├── README_ZH.md                      # Simplified Chinese documentation
├── start-all.ps1 / stop-all.ps1      # Start and stop the local stack
│
├── DeepAnalyze/                      # Upstream DeepAnalyze project
│   └── demo/chat_v2/                 # Core DataAI workspace
│       ├── backend_app/              # FastAPI backend
│       ├── frontend/                 # Next.js frontend
│       ├── demo_datasets_20260815/   # Built-in datasets
│       ├── tests/                    # Backend tests
│       ├── .env.example              # Configuration template
│       └── backend.py                # Backend entry point
│
└── WrenAI/                           # Included WrenAI source
    ├── core/                         # Wren core and CLI packages
    ├── docs/                         # Documentation
    ├── sdk/                          # SDKs
    ├── skills/                       # Agent skills
    ├── examples/                     # Semantic-layer examples
    └── evals/                        # Evaluation scripts and data
```

Local build products such as `.venv/`, `target/`, `node_modules/`, `__pycache__/`, compiled extensions, and temporary caches are excluded through `.gitignore`.

## Configuration

Backend configuration lives in `DeepAnalyze/demo/chat_v2/.env`. Start from [`DeepAnalyze/demo/chat_v2/.env.example`](DeepAnalyze/demo/chat_v2/.env.example).

| Variable | Description | Default |
| --- | --- | --- |
| `DEEPANALYZE_API_BASE` | LLM inference endpoint | `http://localhost:8000/v1` |
| `DEEPANALYZE_MODEL_PATH` | Model identifier | `DeepAnalyze-8B` |
| `DEEPANALYZE_EXECUTION_MODE` | Code execution mode: `docker` or `local` | `docker` |
| `DEEPANALYZE_EXECUTION_TIMEOUT_SEC` | Per-execution timeout in seconds | `120` |
| `DEEPANALYZE_BACKEND_PORT` / `FRONTEND_PORT` | Service ports | `9000` / `4000` |
| `DEEPANALYZE_CHAT_MAX_ROUNDS` | Maximum agent loop rounds | `12` |
| `DEEPANALYZE_CHAT_MAX_DURATION_SEC` | Maximum session duration in seconds | `900` |
| `DEEPANALYZE_WREN_CLI` | Absolute path to `wren.exe` | Windows-specific |
| `DEEPANALYZE_WREN_SERVICE` | Enable the resident query service | `true` |
| `DEEPANALYZE_WREN_SERVICE_PORT` | Resident query service port | `9471` |
| `DEEPANALYZE_MEMORY_SEMANTIC` | Enable natural-language-to-SQL semantic retrieval | `true` |

## Logs and Tests

| Area | Location |
| --- | --- |
| Backend | `DeepAnalyze/demo/chat_v2/logs/backend.log` and `backend_err.log` |
| WrenAI query service | `DeepAnalyze/demo/chat_v2/logs/wren_service.log` |
| Frontend | `DeepAnalyze/demo/chat_v2/logs/frontend.log` |

Run the backend test suite with:

```powershell
DeepAnalyze\.venv\Scripts\python.exe -m pytest DeepAnalyze\demo\chat_v2\tests -q
```

## Acknowledgements

- [DeepAnalyze](https://github.com/ruc-datalab/DeepAnalyze) by RUC-DataLab
- [WrenAI](https://github.com/Canner/WrenAI) by Canner
