# 启动 DeepAnalyze + WrenAI 组合环境（无 Docker，开发模式）
# 用法：右键"使用 PowerShell 运行"，或 powershell -ExecutionPolicy Bypass -File start-all.ps1

$ErrorActionPreference = "SilentlyContinue"

# ============ 配置区 ============
$DATAAI      = "D:\DataAI"
$DA_DIR      = "$DATAAI\DeepAnalyze\demo\chat_v2"
$DA_PY       = "$DATAAI\DeepAnalyze\.venv\Scripts\python.exe"
$DA_BACKEND_PORT  = 9000
$DA_FRONTEND_PORT = 4000
$WREN_VENV   = "$DATAAI\WrenAI\.venv\Scripts\wren.exe"
$WREN_PROJ   = "$DATAAI\wren-jaffle"
$WREN_MCP_PORT   = 8765
# ================================

function Test-Port($port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Stop-Port($port) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        $conns | ForEach-Object {
            Write-Host "  端口 $port 被占用 (PID $($_.OwningProcess))，停止..." -ForegroundColor Yellow
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  DeepAnalyze + WrenAI 组合环境启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---------- 1. WrenAI MCP 服务 ----------
if (Test-Port $WREN_MCP_PORT) {
    Write-Host "[1/3] WrenAI MCP 服务已在运行 (:$WREN_MCP_PORT)" -ForegroundColor Green
} else {
    Write-Host "[1/3] 启动 WrenAI MCP 服务 (:$WREN_MCP_PORT)..." -ForegroundColor Cyan
    Start-Process -FilePath $WREN_VENV `
        -ArgumentList "serve","mcp","--transport","http","--host","127.0.0.1","--port","$WREN_MCP_PORT","--project",$WREN_PROJ,"--profile","jaffle" `
        -WorkingDirectory $WREN_PROJ -WindowStyle Hidden `
        -RedirectStandardOutput "$WREN_PROJ\mcp.log" `
        -RedirectStandardError "$WREN_PROJ\mcp_err.log"
    Start-Sleep -Seconds 6
    if (Test-Port $WREN_MCP_PORT) {
        Write-Host "      OK: http://127.0.0.1:$WREN_MCP_PORT/mcp" -ForegroundColor Green
    } else {
        Write-Host "      失败，查看 $WREN_PROJ\mcp_err.log" -ForegroundColor Red
    }
}

# ---------- 2. DeepAnalyze 后端 ----------
if (Test-Port $DA_BACKEND_PORT) {
    Write-Host "[2/3] DeepAnalyze 后端已在运行 (:$DA_BACKEND_PORT)" -ForegroundColor Green
} else {
    Write-Host "[2/3] 启动 DeepAnalyze 后端 (:$DA_BACKEND_PORT)..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path "$DA_DIR\logs" | Out-Null
    Start-Process -FilePath $DA_PY -ArgumentList "backend.py" `
        -WorkingDirectory $DA_DIR -WindowStyle Hidden `
        -RedirectStandardOutput "$DA_DIR\logs\backend.log" `
        -RedirectStandardError "$DA_DIR\logs\backend_err.log"
    Start-Sleep -Seconds 8
    if (Test-Port $DA_BACKEND_PORT) {
        Write-Host "      OK: http://localhost:$DA_BACKEND_PORT" -ForegroundColor Green
    } else {
        Write-Host "      失败，查看 $DA_DIR\logs\backend_err.log" -ForegroundColor Red
    }
}

# ---------- 3. DeepAnalyze 前端 ----------
if (Test-Port $DA_FRONTEND_PORT) {
    Write-Host "[3/3] DeepAnalyze 前端已在运行 (:$DA_FRONTEND_PORT)" -ForegroundColor Green
} else {
    Write-Host "[3/3] 启动 DeepAnalyze 前端 (:$DA_FRONTEND_PORT)..." -ForegroundColor Cyan
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c npm run dev -- -p $DA_FRONTEND_PORT > ..\logs\frontend.log 2>&1" `
        -WorkingDirectory "$DA_DIR\frontend" -WindowStyle Hidden
    Start-Sleep -Seconds 15
    if (Test-Port $DA_FRONTEND_PORT) {
        Write-Host "      OK: http://localhost:$DA_FRONTEND_PORT" -ForegroundColor Green
    } else {
        Write-Host "      (首次编译较慢，可稍后刷新)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  全部服务：" -ForegroundColor Cyan
Write-Host "   前端:      http://localhost:$DA_FRONTEND_PORT"
Write-Host "   后端 API:  http://localhost:$DA_BACKEND_PORT"
Write-Host "   Wren MCP:  http://127.0.0.1:$WREN_MCP_PORT/mcp"
Write-Host ""
Write-Host "  停止:  powershell -ExecutionPolicy Bypass -File stop-all.ps1"
Write-Host "  日志:  $DA_DIR\logs\ ; $WREN_PROJ\mcp*.log"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
if ([Environment]::UserInteractive -and $Host.Name -eq "ConsoleHost") {
    Write-Host "按任意键退出此窗口（服务继续后台运行）..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
