# DataAI

**语言 / Language:** [English](README.md) | 简体中文

> **本地化、可治理的对话式数据分析工作台**

DataAI 将 DeepAnalyze 的自主数据科学能力与 WrenAI 的语义层和文本到 SQL 能力整合到同一套本地环境中。用户只需用自然语言提问，即可完成数据查询、探索、代码执行、可视化与报告生成；登录、会话与模型配置均按用户隔离保存。

***

## 项目说明

本仓库整合三个部分，形成一条从自然语言问题到可复现分析结果的完整工作流。

- **[DeepAnalyze](https://github.com/ruc-datalab/DeepAnalyze)** — RUC-DataLab 开源的自主数据科学 Agent（[论文](https://arxiv.org/abs/2510.16872) / [模型](https://huggingface.co/RUC-DataLab/DeepAnalyze-8B)），可自动完成数据探索、代码执行、可视化与报告生成。

- **[WrenAI](https://github.com/Canner/WrenAI)** — Canner 开源的 GenBI 引擎，提供受治理的文本到 SQL 与语义层（MDL）。本仓库以 **`WrenAI/`** 子目录纳入上游源码，便于直接引用、查阅并本地构建 Wren CLI。

- **本仓库的核心工作区** — `DeepAnalyze/demo/chat_v2/`，把 DeepAnalyze 与 WrenAI 桥接成一个开箱即用的对话式数据分析应用，提供用户登录、会话隔离、语义层自动构建、代码沙箱执行与模型配置持久化。

数据源包括会话内上传的 CSV、Excel、SQLite 等文件。系统会自动构建 DuckDB 与动态 MDL，并将其接入 WrenAI 语义层；模型可通过注入的 `wren_query()` 函数对上传数据执行受治理的 SQL 查询。

---

## 架构

```
┌─────────────────────────────────────────────────────┐
│  浏览器  http://localhost:4000                       │
│  (Next.js 前端：登录、聊天、工作区文件管理)              │
└──────────────────────┬──────────────────────────────┘
                       │ /api 同源代理 (携带认证 Cookie)
┌──────────────────────▼──────────────────────────────┐
│  DeepAnalyze 后端  http://localhost:9000             │
│  (FastAPI：认证、会话管理、代码执行、报告导出)           │
│  └─ 启动时拉起 WrenAI 查询常驻服务  127.0.0.1:9471    │
└───────┬─────────────────────────────┬───────────────┘
        │                             │
        │ OpenAI 协议                  │ wren_query() 语义层桥接
┌───────▼────────┐          ┌─────────▼───────────────┐
│  LLM 推理服务   │          │  WrenAI  venv 内的        │
│  vLLM :8000    │          │  wren.exe / wren query    │
│  或自定义 API    │          │  (语义层/指标口径治理)      │
└────────────────┘          └─────────┬───────────────┘
                                      │ DuckDB
                              ┌───────▼────────┐
                              │  每会话上传数据    │
                              │  (CSV/Excel/    │
                              │   SQLite/DuckDB)│
                              └─────────────────┘
```

> 注：WrenAI **不作为常驻 HTTP/MCP 服务独立运行**。后端启动时按需拉起一个查询常驻服务（`127.0.0.1:9471`，端口由 `DEEPANALYZE_WREN_SERVICE_PORT` 控制）以省掉每次 `wren.exe query` 的进程启动开销；不可达时执行侧自动回退 CLI 子进程，查询仍可完成。Docker 模式下网络隔离，执行侧始终走 CLI。

***

## 目录结构

```
DataAI/
├── README.md                       # 本文件
├── start-all.ps1 / stop-all.ps1    # 一键启动 / 停止
├── .gitignore                      # 细粒度排除 WrenAI/ 内的构建产物
│
├── DeepAnalyze/                    # DeepAnalyze 主项目（上游）
│   ├── .venv/                      # Python 虚拟环境（不入库）
│   └── demo/
│       └── chat_v2/                # 本仓库核心工作区
│           ├── backend_app/        # FastAPI 后端
│           │   ├── routers/        #   auth / chat / session / user / workspace / semantic / code_editing / export ...
│           │   └── services/       #   认证、会话状态、代码执行、
│           │                       #   语义层构建、wren 查询常驻服务、...
│           ├── frontend/           # Next.js 前端（聊天 UI + 工作区管理）
│           ├── demo_datasets_20260815/  # 内置示例数据集（4 组，中英文问题）
│           ├── tests/              # 后端单元测试
│           ├── auth/               # 用户账号与模型配置（运行时生成，不入库）
│           ├── workspace/          # 每用户会话工作区（运行时生成，不入库）
│           ├── logs/               # 运行日志（运行时生成，不入库）
│           ├── .env.example        # 后端配置模板
│           ├── backend.py          # 后端入口
│           └── start.bat / stop.bat
│
└── WrenAI/                         # WrenAI 上游源码（已纳入版本控制）
    ├── core/                       #   wren / wren-core / wren-core-py / wren-core-wasm
    ├── docs/                       #   概念、入门、指南、SDK、参考
    ├── sdk/                        #   wren-langchain / wren-pydantic
    ├── skills/                     #   Claude/Agent 可消费的 wren skill
    ├── examples/
    │   └── v5-jaffle/              # 语义层示例项目（模型/Cube/口径定义）
    ├── evals/                      #   评测脚本与数据
    └── .venv/                      # Python 虚拟环境（不入库，见 .gitignore）
```

> `WrenAI/` 内已通过 `.gitignore` 排除 `.venv/`、`target/`、`node_modules/`、`__pycache__/`、`*.pyd`、`*.so`、`*.egg-info/`、`build/`、`dist/`、`*.sqlite`、`local_cache/`、`.tmp/` 等本地构建产物，避免 127MB 的 `wren_core.pyd` 触发 GitHub 100MB 限制。

***

## 快速开始

### 前置条件

- Windows + PowerShell（脚本为 PowerShell）

- Python 虚拟环境：`DeepAnalyze/.venv`（依赖见 [DeepAnalyze/requirements.txt](DeepAnalyze/requirements.txt)）

- Node.js（前端依赖已通过 `pnpm-lock.yaml` / `package-lock.json` 锁定，`npm install` 即用）

- WrenAI 环境：`WrenAI/.venv`，含 `wren.exe` 与同目录的 `python.exe`。首次构建见下文

- LLM 推理：本地 vLLM（默认 `http://localhost:8000/v1`）或任意 OpenAI 兼容 API（前端设置里切换为"自定义模型"）

### 一次性准备

```powershell
# 1) DeepAnalyze 后端虚拟环境（如不存在）
python -m venv DeepAnalyze\.venv
DeepAnalyze\.venv\Scripts\pip install -r DeepAnalyze\requirements.txt

# 2) WrenAI venv + wren CLI（首次需构建 wren-core；耗时较长）
cd WrenAI
python -m venv .venv
.\.venv\Scripts\pip install -e ".\core\wren-core-base" -e ".\core\wren-core-py" -e ".\core\wren"
cd ..
```

> DeepAnalyze 后端默认指向 `D:\DataAI\WrenAI\.venv\Scripts\wren.exe`（见 `DEEPANALYZE_WREN_CLI`）。若你的路径不同，复制 `DeepAnalyze/demo/chat_v2/.env.example` 为 `.env` 并修改该变量。

### 启动

```powershell
powershell -ExecutionPolicy Bypass -File start-all.ps1
```

依次启动后端与前端（已运行则跳过；WrenAI 查询常驻服务由后端内部按需拉起）：

| 顺序 | 服务             | 地址                      |
| -- | -------------- | ----------------------- |
| 1  | DeepAnalyze 后端 | <http://localhost:9000> |
| 2  | DeepAnalyze 前端 | <http://localhost:4000> |
| —  | WrenAI 查询服务    | 127.0.0.1:9471（后端拉起）    |

打开 <http://localhost:4000> 即可使用。

### 停止

```powershell
powershell -ExecutionPolicy Bypass -File stop-all.ps1
```

将一并清理 9000 / 4000 / 9471 三个端口上的进程。

***

## 功能说明

### 用户登录与会话隔离

- 首次使用注册账号（用户名小写字母 / 数字 / 下划线 / 连字符，3-32 位；密码至少 4 位）

- 会话记录按用户隔离存储于服务端（`workspace/u{用户名}__...`），登录同一账号即可恢复，越权访问返回 403

- 首个注册用户自动认领历史无主会话

- 左上角用户菜单：历史会话列表、切换会话、新建会话、退出登录

### 模型配置（按用户保存）

- 设置面板中配置模型来源：本地 vLLM / 和鲸 API / 自定义（OpenAI 兼容）

- **保存配置**：存到服务端当前用户名下，换浏览器 / 设备登录后自动恢复

- **检测连接**：向所选模型发一条真实请求，返回成功延迟或失败原因

- 配置按用户名隔离，不会跨用户串扰

### 数据分析

- 上传 CSV / Excel / SQLite 等文件，或加载内置示例数据集（4 组，中英文问题，见 `DeepAnalyze/demo/chat_v2/demo_datasets_20260815/`）

- 自然语言描述分析需求，Agent 自动生成并执行 Python 代码（默认 Docker 沙箱，可选本地模式）

- 生成的图表、表格、报告存入会话工作区 `generated/` 目录，支持预览与打包下载

- 通过 `wren_query()` / `wren_dry_run()` 走 WrenAI 语义层查询上传数据；`wren_describe()` 把列含义登记到数据字典，后续轮次自动注入；`wren_remember()` 把成功的 NL→SQL 写入个人查询记忆，跨会话复用

- 上下文过长时自动压缩，确保不超出模型窗口

### WrenAI 语义层

- 每个会话首次上传数据时自动构建：CSV / Excel 导入 DuckDB，生成动态 MDL

- 引擎目录：`workspace/<session>/.deepanalyze/wren/`（`mdl.json` + `conn.json` + DuckDB）

- 表名 / 列名沿用原文件（清理为合法标识符，中文保留）

- 后续查询经由常驻查询服务（`127.0.0.1:9471`）执行，比 CLI 子进程快一个数量级；不可达时自动回退 CLI

- Docker 模式下网络隔离，常驻服务无法被容器访问，执行侧始终走 CLI

***

## 配置

后端配置文件 `DeepAnalyze/demo/chat_v2/.env`（参照 [.env.example](DeepAnalyze/demo/chat_v2/.env.example)）。常用项：

| 变量                                           | 说明                         | 默认                                        |
| -------------------------------------------- | -------------------------- | ----------------------------------------- |
| `DEEPANALYZE_API_BASE`                       | LLM 推理地址                   | `http://localhost:8000/v1`                |
| `DEEPANALYZE_MODEL_PATH`                     | 模型标识                       | `DeepAnalyze-8B`                          |
| `DEEPANALYZE_EXECUTION_MODE`                 | 代码执行模式（`docker` / `local`） | `docker`                                  |
| `DEEPANALYZE_EXECUTION_TIMEOUT_SEC`          | 单次执行超时（秒）                  | `120`                                     |
| `DEEPANALYZE_BACKEND_PORT` / `FRONTEND_PORT` | 服务端口                       | `9000` / `4000`                           |
| `DEEPANALYZE_CHAT_MAX_ROUNDS`                | Agent 循环轮数上限               | `12`                                      |
| `DEEPANALYZE_CHAT_MAX_DURATION_SEC`          | 单次会话总时长上限（秒）               | `900`                                     |
| `DEEPANALYZE_WREN_CLI`                       | `wren.exe` 完整路径            | `D:\DataAI\WrenAI\.venv\Scripts\wren.exe` |
| `DEEPANALYZE_WREN_SERVICE`                   | 是否启用常驻查询服务                 | `true`                                    |
| `DEEPANALYZE_WREN_SERVICE_PORT`              | 常驻查询服务端口                   | `9471`                                    |
| `DEEPANALYZE_MEMORY_SEMANTIC`                | 是否启用 NL→SQL 语义召回           | `true`                                    |

***

## 日志

- 后端：`DeepAnalyze/demo/chat_v2/logs/backend.log` / `backend_err.log`

- WrenAI 查询服务：`DeepAnalyze/demo/chat_v2/logs/wren_service.log`

- 前端：`DeepAnalyze/demo/chat_v2/logs/frontend.log`

***

## 测试

```powershell
DeepAnalyze\.venv\Scripts\python.exe -m pytest DeepAnalyze\demo\chat_v2\tests -q
```

***

## 致谢

- [DeepAnalyze](https://github.com/ruc-datalab/DeepAnalyze)（RUC-DataLab）

- [WrenAI](https://github.com/Canner/WrenAI)（Canner）
