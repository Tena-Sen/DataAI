# Chat Demo

`demo/chat_v2` 是 DeepAnalyze 的浏览器交互 Demo，包含后端 API、workspace 文件层、前端界面，以及本地和 Docker 两种执行模式。

[English README](./README.md)

## 功能概览

- 支持在 workspace 中上传和管理表格、数据库、文本、日志与文档
- 支持常见 workspace 文件的在线预览
- 支持流式展示 `<Analyze> / <Understand> / <Code> / <Execute> / <File> / <Answer>` 区块
- 支持在 workspace 中执行 Python 分析代码
- 支持导出 Markdown 和 PDF 报告
- 支持中英文界面切换
- 支持 local / docker 两种代码执行模式
- 支持明确选择每次分析使用的 workspace 文件
- 支持按 session 恢复任务配置、聊天轨迹和执行历史
- 自动与手动代码执行都会保存脚本版本、diff、输出和关联产物

## 运行前准备

### 1. 模型服务

先启动 DeepAnalyze 模型服务，例如：

```bash
vllm serve DeepAnalyze-8B
```

默认连接 `http://localhost:8000` 附近的 OpenAI 兼容接口。

### 2. Python 与 Node.js

建议：

- Python 使用现有 DeepAnalyze 环境，例如 `deepanalyze`
- Node.js 使用可运行当前 Next.js 前端的版本

首次运行前端前先安装依赖：

```bash
cd demo/chat_v2/frontend
npm install
cd ..
```

### 3. 环境变量

使用示例配置文件：

```bash
cd demo/chat_v2
cp .env.example .env
```

Windows：

```powershell
cd demo/chat_v2
Copy-Item .env.example .env
```

## 执行模式

### local 模式

local 模式仅用于可信的开发环境。它会在宿主机直接运行生成的 Python 代码，默认禁用，必须显式接受风险：

```env
DEEPANALYZE_EXECUTION_MODE=local
DEEPANALYZE_ALLOW_UNSAFE_LOCAL_EXECUTION=true
```

### docker 模式

Docker 是默认且满足沙箱隔离要求的执行模式。每个 session 使用独立容器，且只挂载该 session 的 workspace。默认关闭网络，并通过 `.env` 限制内存、CPU、PID、只读容器文件系统、非 root 用户和执行时间：

```env
DEEPANALYZE_EXECUTION_MODE=docker
```

后端启动时会检查 Docker CLI 和 Docker 守护进程。如果默认执行镜像不存在，系统会使用项目内的 `Dockerfile.exec` 自动构建。首次启动需要下载基础镜像和 Python 依赖，因此耗时会更长。

如需由外部部署流程管理镜像，可禁用自动构建：

```env
DEEPANALYZE_DOCKER_AUTO_BUILD=false
```

也可以手动构建：

示例：

```bash
cd demo/chat_v2
docker build -t deepanalyze-chat-exec:latest -f Dockerfile.exec .
```

可以通过 `DEEPANALYZE_DOCKER_MEMORY`、`DEEPANALYZE_DOCKER_CPUS`、`DEEPANALYZE_DOCKER_PIDS_LIMIT` 和 `DEEPANALYZE_DOCKER_NETWORK_MODE` 调整资源限制。

## 安全边界与 Agent 预算

- session ID 和所有 workspace 路径都会校验，不能逃逸到 workspace 根目录之外。
- 上传采用分块写入，并限制单文件大小、session 总容量和文件数量。
- 模型输出必须是完整的结构化动作，且只能包含一个位于末尾的 `<Code>` 或 `<Answer>`；不完整的代码不会执行。
- 同一个 session 同时只允许一个分析或手动执行任务。
- 分别限制 Agent 轮次、响应长度、总时长和单次代码时长；`/chat/stop` 也会取消正在运行的代码。

## Session 状态与统一执行

每个 session 的状态保存在执行 workspace 之外的 `.session_state/<session>/session.json`，不会挂载进沙箱容器，也不会由 workspace API 暴露；清空用户 workspace 文件时仍会保留会话状态。浏览器优先从服务端恢复状态，仅将按 session 隔离的 localStorage 缓存作为离线回退。

Agent 自动生成的 `<Code>` 与代码工作台手动复跑统一经过同一个执行服务。每次运行都会在 `generated/code/` 保存版本化脚本、登记新增或修改的 artifacts、记录自然语言修改指令与统一 diff，并生成可进入主聊天轨迹和报告导出的 Code/Execute/File 内容。

对话输入区默认使用**自动模式**。切换到**手动模式**后，后端会在每次代码执行完成后暂停：此时浏览器已经显示 Execute 区块，但执行结果尚未发送给模型。用户可以直接继续，也可以先在输入框中填写追加指令再继续。非空追加指令会按以下固定格式附加到待发送的执行反馈后：

```text
<执行输出>

# Additional Instruction
<用户追加指令>
```

待续上下文保存在服务端 session 状态中，因此刷新浏览器后仍能恢复“等待继续”状态，同时 session API 不会暴露内部模型对话。

## 如何运行

### Linux / macOS

```bash
cd demo/chat_v2
bash start.sh
```

停止：

```bash
cd demo/chat_v2
bash stop.sh
```

### Windows

```bat
cd demo\chat
start.bat
```

停止：

```bat
cd demo\chat
stop.bat
```

默认地址：

- 前端：`http://localhost:4000`
- 后端 API：`http://localhost:9000`
- 文件服务：`http://localhost:8100`

端口可在 `.env` 中修改。启动和停止脚本都会读取这些配置，启动脚本还会自动让前端连接到配置后的后端地址：

```env
DEEPANALYZE_BACKEND_PORT=8300
DEEPANALYZE_FILE_SERVER_PORT=8100
FRONTEND_PORT=4000
```

## PDF 导出

PDF 导出依赖：

- `pypandoc`
- `pandoc`
- `xelatex`

行为说明：

- 如果缺少 `pandoc`，后端会尝试自动下载（默认开启）。
- `xelatex` 仍是必需项，需要手动安装。
- 可通过以下环境变量控制：
  - `DEEPANALYZE_PDF_AUTO_DOWNLOAD_PANDOC`（默认 `true`）
  - `DEEPANALYZE_PDF_PANDOC_CACHE_DIR`（可选，指定 pandoc 缓存目录）

## 目录说明

- `backend.py`：后端启动入口
- `backend_app/`：FastAPI 后端实现
- `frontend/`：Next.js 前端
- `Dockerfile.exec`：执行镜像定义
- `workspace/`：按 session 隔离的工作区
- `logs/`：运行日志
