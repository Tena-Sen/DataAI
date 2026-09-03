# DataAI

DeepAnalyze + WrenAI 组合的本地数据分析环境：通过自然语言对话完成数据查询、分析与可视化，内置用户登录与按用户隔离的会话记录。

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
└───────┬─────────────────────────────┬───────────────┘
        │                             │
        │ OpenAI 协议                  │ wren_query() 语义层桥接
┌───────▼────────┐          ┌─────────▼───────────────┐
│  LLM 推理服务   │          │  WrenAI MCP  :8765       │
│  vLLM :8000    │          │  (SQL 语义层/指标口径治理)  │
│  或自定义 API    │          └─────────┬───────────────┘
└────────────────┘                    │ DuckDB
                              ┌───────▼────────┐
                              │  jaffle_shop    │
                              │  .duckdb        │
                              └─────────────────┘
```

- **DeepAnalyze**：人大 RUC-DataLab 开源的自主数据科学 Agent（[论文](https://arxiv.org/abs/2510.16872) / [模型](https://huggingface.co/RUC-DataLab/DeepAnalyze-8B)），自动完成数据探索、代码执行、可视化与报告生成
- **WrenAI**：语义层，将业务口径（模型/视图/Cube）治理后对外提供受控 SQL 查询，Agent 通过注入的 `wren_query()` 函数调用
- 数据源为 dbt jaffle_shop 演示库（DuckDB）

## 目录结构

```
DataAI/
├── DeepAnalyze/              # DeepAnalyze 主项目
│   ├── .venv/                # Python 虚拟环境（不入库）
│   └── demo/chat_v2/         # 对话式 Demo（本仓库主要工作区）
│       ├── backend_app/      # FastAPI 后端
│       │   ├── routers/      #   auth / chat / session / user / workspace ...
│       │   └── services/     #   认证、会话状态、代码执行 ...
│       ├── frontend/         # Next.js 前端
│       ├── auth/             # 用户账号与模型配置（运行时生成，不入库）
│       ├── workspace/        # 每用户会话工作区（运行时生成，不入库）
│       └── .env              # 本地配置（不入库，参照 .env.example）
├── wren-jaffle/              # WrenAI 语义层项目（模型/视图/Cube 定义）
├── WrenAI/                   # WrenAI 上游克隆（不入库，见下文）
├── jaffle_shop_duckdb/       # dbt jaffle_shop 上游克隆（不入库，见下文）
├── jaffle_shop.duckdb        # DuckDB 数据文件
├── start-all.ps1             # 一键启动
└── stop-all.ps1              # 一键停止
```

## 快速开始

### 前置条件

- Windows + PowerShell
- Python 虚拟环境：`DeepAnalyze/.venv`（依赖见 [requirements.txt](DeepAnalyze/requirements.txt)）
- Node.js（前端 `npm install` 已就绪）
- WrenAI 环境：`WrenAI/.venv`（含 `wren.exe`）
- LLM 推理：本地 vLLM（默认 `http://localhost:8000/v1`）或任意 OpenAI 兼容 API（前端设置里切换为"自定义模型"）

> 恢复上游克隆（本仓库未包含）：
> ```powershell
> git clone https://github.com/Canner/WrenAI.git
> git clone https://github.com/dbt-labs/jaffle_shop_duckdb.git
> ```

### 启动

```powershell
powershell -ExecutionPolicy Bypass -File start-all.ps1
```

依次启动三个服务（已运行则跳过）：

| 顺序 | 服务 | 地址 |
|---|---|---|
| 1 | WrenAI MCP | http://127.0.0.1:8765/mcp |
| 2 | DeepAnalyze 后端 | http://localhost:9000 |
| 3 | DeepAnalyze 前端 | http://localhost:4000 |

打开 http://localhost:4000 即可使用。

### 停止

```powershell
powershell -ExecutionPolicy Bypass -File stop-all.ps1
```

## 功能说明

### 用户登录与会话隔离
- 首次使用注册账号（用户名小写字母/数字/下划线/连字符，3-32 位；密码至少 4 位）
- 会话记录按用户隔离存储于服务端（`workspace/u{用户名}__...`），登录同一账号即可恢复，越权访问返回 403
- 首个注册用户自动认领历史无主会话
- 左上角用户菜单：历史会话列表、切换会话、新建会话、退出登录

### 模型配置（按用户保存）
- 设置面板中配置模型来源：本地 vLLM / 和鲸 API / 自定义（OpenAI 兼容）
- **保存配置**：存到服务端当前用户名下，换浏览器/设备登录后自动恢复
- **检测连接**：向所选模型发一条真实请求，返回成功延迟或失败原因

### 数据分析
- 上传 CSV/XLSX/SQLite 等文件，或加载内置示例数据集
- 自然语言描述分析需求，Agent 自动生成并执行 Python 代码
- 生成的图表、表格、报告存入会话工作区 `generated/` 目录，支持预览与打包下载
- 可通过 `wren_query()` 走 WrenAI 语义层查询治理后的业务数据

## 配置

后端配置文件 `DeepAnalyze/demo/chat_v2/.env`（参照 [.env.example](DeepAnalyze/demo/chat_v2/.env.example)），常用项：

| 变量 | 说明 | 默认 |
|---|---|---|
| `DEEPANALYZE_API_BASE` | LLM 推理地址 | `http://localhost:8000/v1` |
| `DEEPANALYZE_EXECUTION_MODE` | 代码执行模式（docker/local） | docker |
| `DEEPANALYZE_EXECUTION_TIMEOUT_SEC` | 单次执行超时（秒） | 120 |
| `DEEPANALYZE_BACKEND_PORT` / `FRONTEND_PORT` | 服务端口 | 9000 / 4000 |
| `DEEPANALYZE_CHAT_MAX_ROUNDS` | Agent 循环轮数上限 | 12 |

WrenAI 桥接地址由 `DEEPANALYZE_WREN_CLI` / `DEEPANALYZE_WREN_PROJECT` 指定。

## 日志

- 后端：`DeepAnalyze/demo/chat_v2/logs/`
- WrenAI MCP：`wren-jaffle/mcp.log`、`mcp_err.log`
- 前端：`DeepAnalyze/demo/chat_v2/logs/frontend.log`

## 致谢

- [DeepAnalyze](https://github.com/ruc-datalab/DeepAnalyze)（RUC-DataLab）
- [WrenAI](https://github.com/Canner/WrenAI)（Canner）
- [jaffle_shop_duckdb](https://github.com/dbt-labs/jaffle_shop_duckdb)（dbt Labs）
