<div align="center">

# DataAI

**本地化、可治理的对话式数据分析工作台**

[English](README.md) · [简体中文](README_ZH.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-前端-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-后端-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![DuckDB](https://img.shields.io/badge/DuckDB-分析引擎-FFF000?logo=duckdb&logoColor=black)](https://duckdb.org/)

</div>

DataAI 将 [DeepAnalyze](https://github.com/ruc-datalab/DeepAnalyze) 与 [WrenAI](https://github.com/Canner/WrenAI) 整合为本地化的对话式数据分析工作台。用户可以使用自然语言提问，查询上传的数据，生成并执行分析代码，创建可视化图表并导出报告；账号、会话与模型配置均按用户隔离保存，查询过程由语义层统一治理。

> **从一个自然语言问题，到一份可复现的分析结果。**

## 为什么选择 DataAI？

DataAI 将自主数据科学能力与可治理的语义层连接起来。用户无需在数据库客户端、Notebook、图表工具和报告编辑器之间反复切换，即可在一个对话式工作区内完成完整分析流程。

| 能力 | 说明 |
| --- | --- |
| 自然语言分析 | 描述分析目标，由 Agent 自动规划后续步骤。 |
| 受治理的文本到 SQL | 通过 WrenAI 语义层与动态 MDL 查询上传数据。 |
| 可复现执行 | 在 Docker 沙箱或本地模式中生成并执行 Python 分析代码。 |
| 工作区隔离 | 按用户隔离账号、会话、上传数据、模型配置与生成结果。 |
| 分析交付物 | 在会话工作区内预览并下载生成的图表、表格与报告。 |

## 系统架构

```text
┌────────────────────────────────────────────────────────────┐
│  浏览器 · http://localhost:4000                           │
│  Next.js 界面 · 登录 · 对话 · 工作区文件管理              │
└──────────────────────────┬─────────────────────────────────┘
                           │ 同源 /api 代理 + 认证 Cookie
┌──────────────────────────▼─────────────────────────────────┐
│  DeepAnalyze 后端 · http://localhost:9000                 │
│  FastAPI · 认证 · 会话 · 代码执行 · 报告导出              │
│  └─ 按需启动 WrenAI 查询服务                              │
└───────────────┬──────────────────────────┬────────────────┘
                │ OpenAI 兼容 API           │ wren_query() 桥接
┌───────────────▼──────────────┐  ┌────────▼─────────────────┐
│ LLM 推理服务                 │  │ WrenAI 环境              │
│ vLLM :8000 或自定义 API      │  │ 语义层 · MDL              │
└──────────────────────────────┘  └────────┬─────────────────┘
                                           │ DuckDB
                                  ┌────────▼─────────┐
                                  │ 会话数据          │
                                  │ CSV · Excel      │
                                  │ SQLite · DuckDB  │
                                  └───────────────────┘
```

WrenAI 不会作为独立的常驻 HTTP 或 MCP 应用运行。后端启动时可以在 `127.0.0.1:9471` 按需启动查询服务，避免每次请求都重新启动 `wren.exe query`。如果该服务不可用，执行层会自动回退到 CLI 子进程。在 Docker 模式下，由于网络隔离，执行层始终使用 CLI 回退路径。

## 快速开始

### 环境要求

- Windows 与 PowerShell；项目提供的启动和停止脚本使用 PowerShell。
- `DeepAnalyze` 与 `WrenAI` 对应的 Python 虚拟环境。
- Node.js，以及 npm 或 pnpm。
- 本地 vLLM 服务，或任意 OpenAI 兼容 API。默认地址为 `http://localhost:8000/v1`。

### 1. 准备运行环境

```powershell
# DeepAnalyze 后端
python -m venv DeepAnalyze\.venv
DeepAnalyze\.venv\Scripts\pip install -r DeepAnalyze\requirements.txt

# WrenAI 与 Wren CLI
cd WrenAI
python -m venv .venv
.\.venv\Scripts\pip install -e ".\core\wren-core-base" -e ".\core\wren-core-py" -e ".\core\wren"
cd ..
```

后端默认使用 `D:\DataAI\WrenAI\.venv\Scripts\wren.exe`。如果你的路径不同，请将 `DeepAnalyze/demo/chat_v2/.env.example` 复制为 `.env`，并修改 `DEEPANALYZE_WREN_CLI`。

### 2. 启动 DataAI

```powershell
powershell -ExecutionPolicy Bypass -File start-all.ps1
```

| 服务 | 地址 | 作用 |
| --- | --- | --- |
| DeepAnalyze 后端 | <http://localhost:9000> | API、会话、代码执行与导出 |
| DataAI 前端 | <http://localhost:4000> | 登录、对话与工作区界面 |
| WrenAI 查询服务 | `127.0.0.1:9471` | 由后端按需启动 |

在浏览器中打开 <http://localhost:4000> 即可使用。

### 3. 停止 DataAI

```powershell
powershell -ExecutionPolicy Bypass -File stop-all.ps1
```

该命令会停止与 `9000`、`4000` 和 `9471` 端口相关的进程。

## 核心功能

### 用户认证与会话隔离

- 首次使用时注册账号。用户名支持小写字母、数字、下划线和连字符，长度为 3–32 个字符。
- 会话按当前用户存储在服务端，重新登录后可以恢复。
- 跨用户访问会返回 `403`。
- 首个注册用户可以认领尚未绑定用户的历史会话。
- 用户菜单支持查看会话历史、切换会话、新建会话和退出登录。

### 按用户保存模型配置

- 可选择本地 vLLM、和鲸 API 或其他 OpenAI 兼容的自定义接口。
- 配置保存到服务端，并可在不同浏览器或设备登录后自动恢复。
- 通过真实模型请求检测连接，并查看延迟或失败原因。
- 模型配置按用户名隔离。

### 数据分析流程

- 上传 CSV、Excel 或 SQLite 文件，也可以加载四组内置示例数据集。
- 使用自然语言描述分析任务。Agent 默认在 Docker 沙箱中生成并执行 Python 代码，也支持本地模式。
- 图表、表格和报告保存到会话的 `generated/` 目录，可预览和下载。
- 使用 `wren_query()` 与 `wren_dry_run()` 执行语义层查询，使用 `wren_describe()` 登记列含义，使用 `wren_remember()` 跨会话复用成功的自然语言到 SQL 查询。
- 自动压缩过长上下文，避免超出模型上下文窗口。

### WrenAI 语义层

- 会话首次上传数据时，CSV 和 Excel 文件会导入 DuckDB，并自动生成动态 MDL。
- 每个会话的引擎位于 `workspace/<session>/.deepanalyze/wren/`，包含 `mdl.json`、`conn.json` 和 DuckDB 数据库。
- 原始表名和列名在规范化为合法标识符后继续保留，中文名称也会保留。
- 后续查询优先使用 `127.0.0.1:9471` 的常驻服务；服务不可用时自动回退到 CLI。

## 仓库结构

```text
DataAI/
├── README.md                         # English 文档
├── README_ZH.md                      # 简体中文文档
├── start-all.ps1 / stop-all.ps1      # 启动和停止本地服务
│
├── DeepAnalyze/                      # DeepAnalyze 上游项目
│   └── demo/chat_v2/                 # DataAI 核心工作区
│       ├── backend_app/              # FastAPI 后端
│       ├── frontend/                 # Next.js 前端
│       ├── demo_datasets_20260815/   # 内置示例数据集
│       ├── tests/                    # 后端测试
│       ├── .env.example              # 配置模板
│       └── backend.py                # 后端入口
│
└── WrenAI/                           # 纳入仓库的 WrenAI 源码
    ├── core/                         # Wren 核心与 CLI 包
    ├── docs/                         # 文档
    ├── sdk/                          # SDK
    ├── skills/                       # Agent 技能
    ├── examples/                     # 语义层示例
    └── evals/                        # 评测脚本与数据
```

`.venv/`、`target/`、`node_modules/`、`__pycache__/`、编译扩展和临时缓存等本地构建产物已通过 `.gitignore` 排除。

## 配置

后端配置位于 `DeepAnalyze/demo/chat_v2/.env`。请以 [`DeepAnalyze/demo/chat_v2/.env.example`](DeepAnalyze/demo/chat_v2/.env.example) 为模板。

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `DEEPANALYZE_API_BASE` | LLM 推理地址 | `http://localhost:8000/v1` |
| `DEEPANALYZE_MODEL_PATH` | 模型标识 | `DeepAnalyze-8B` |
| `DEEPANALYZE_EXECUTION_MODE` | 代码执行模式：`docker` 或 `local` | `docker` |
| `DEEPANALYZE_EXECUTION_TIMEOUT_SEC` | 单次执行超时时间（秒） | `120` |
| `DEEPANALYZE_BACKEND_PORT` / `FRONTEND_PORT` | 服务端口 | `9000` / `4000` |
| `DEEPANALYZE_CHAT_MAX_ROUNDS` | Agent 最大循环轮数 | `12` |
| `DEEPANALYZE_CHAT_MAX_DURATION_SEC` | 单次会话最长时间（秒） | `900` |
| `DEEPANALYZE_WREN_CLI` | `wren.exe` 的绝对路径 | Windows 路径 |
| `DEEPANALYZE_WREN_SERVICE` | 是否启用常驻查询服务 | `true` |
| `DEEPANALYZE_WREN_SERVICE_PORT` | 常驻查询服务端口 | `9471` |
| `DEEPANALYZE_MEMORY_SEMANTIC` | 是否启用自然语言到 SQL 的语义召回 | `true` |

## 日志与测试

| 范围 | 位置 |
| --- | --- |
| 后端 | `DeepAnalyze/demo/chat_v2/logs/backend.log` 与 `backend_err.log` |
| WrenAI 查询服务 | `DeepAnalyze/demo/chat_v2/logs/wren_service.log` |
| 前端 | `DeepAnalyze/demo/chat_v2/logs/frontend.log` |

运行后端测试：

```powershell
DeepAnalyze\.venv\Scripts\python.exe -m pytest DeepAnalyze\demo\chat_v2\tests -q
```

## 致谢

- [DeepAnalyze](https://github.com/ruc-datalab/DeepAnalyze)，由 RUC-DataLab 开源
- [WrenAI](https://github.com/Canner/WrenAI)，由 Canner 开源
