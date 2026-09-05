# 启动 DeepAnalyze + WrenAI 组合环境（无 Docker，开发模式）
# 用法：右键"使用 PowerShell 运行"，或 powershell -ExecutionPolicy Bypass -File start-all.ps1

$ErrorActionPreference = "SilentlyContinue"

# ============ 配置区 ============
$DATAAI      = "D:\DataAI"
$DA_DIR      = "$DATAAI\DeepAnalyze\demo\chat_v2"
$DA_PY       = "$DATAAI\DeepAnalyze\.venv\Scripts\python.exe"
$DA_BACKEND_PORT  = 9000
$DA_FRONTEND_PORT = 4000
# ================================

function Test-Port($port) {
    # 主用 Get-NetTCPConnection；某些环境下它会静默失败，回退到 TCP 直连探测
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        return $true
    }
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
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
Write-Host "  DeepAnalyze 环境启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---------- 1/2. DeepAnalyze 后端 ----------
if (Test-Port $DA_BACKEND_PORT) {
    Write-Host "[1/2] DeepAnalyze 后端已在运行 (:$DA_BACKEND_PORT)" -ForegroundColor Green
} else {
    Write-Host "[1/2] 启动 DeepAnalyze 后端 (:$DA_BACKEND_PORT)..." -ForegroundColor Cyan
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

# ---------- 2/2. DeepAnalyze 前端 ----------
if (Test-Port $DA_FRONTEND_PORT) {
    Write-Host "[2/2] DeepAnalyze 前端已在运行 (:$DA_FRONTEND_PORT)" -ForegroundColor Green
} else {
    Write-Host "[2/2] 启动 DeepAnalyze 前端 (:$DA_FRONTEND_PORT)..." -ForegroundColor Cyan
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
Write-Host ""
Write-Host "  停止:  powershell -ExecutionPolicy Bypass -File stop-all.ps1"
Write-Host "  日志:  $DA_DIR\logs\"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
# 双击/交互终端中暂停看结果；被脚本/管道调用（输入重定向）时直接退出
if ([Environment]::UserInteractive -and $Host.Name -eq "ConsoleHost" -and -not [Console]::IsInputRedirected) {
    Write-Host "按任意键退出此窗口（服务继续后台运行）..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
