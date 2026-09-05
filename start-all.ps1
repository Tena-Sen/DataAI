# 启动 DeepAnalyze + WrenAI 组合环境（无 Docker，开发模式）
# 启动顺序：
#   1/3 DeepAnalyze 后端 (:9000)   — backend.py
#   2/3 DeepAnalyze 前端 (:4000)   — npm run dev
#   3/3 Wren 查询服务  (:9471)    — 通常由 backend 在 lifespan 自动拉起，
#                                    兜底逻辑：若 backend 启动 20 秒后 9471
#                                    仍未监听，则显式拉 wren_query_service_driver.py
# 用法：右键"使用 PowerShell 运行"，或 powershell -ExecutionPolicy Bypass -File start-all.ps1

$ErrorActionPreference = "SilentlyContinue"

# ============ 配置区 ============
$DATAAI      = "D:\DataAI"
$DA_DIR      = "$DATAAI\DeepAnalyze\demo\chat_v2"
$DA_PY       = "$DATAAI\DeepAnalyze\.venv\Scripts\python.exe"
$WREN_PY     = "$DATAAI\WrenAI\.venv\Scripts\python.exe"
$WREN_DRIVER = "$DA_DIR\backend_app\services\wren_query_service_driver.py"
$WREN_TOKEN  = "$DA_DIR\logs\wren_service.token"
$WREN_LOG    = "$DA_DIR\logs\wren_service.log"
$DA_BACKEND_PORT   = 9000
$DA_FRONTEND_PORT  = 4000
$DA_WREN_PORT      = 9471
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

# ---------- 1/3. DeepAnalyze 后端 ----------
if (Test-Port $DA_BACKEND_PORT) {
    Write-Host "[1/3] DeepAnalyze 后端已在运行 (:$DA_BACKEND_PORT)" -ForegroundColor Green
} else {
    Write-Host "[1/3] 启动 DeepAnalyze 后端 (:$DA_BACKEND_PORT)..." -ForegroundColor Cyan
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

# ---------- 2/3. DeepAnalyze 前端 ----------
if (Test-Port $DA_FRONTEND_PORT) {
    Write-Host "[2/3] DeepAnalyze 前端已在运行 (:$DA_FRONTEND_PORT)" -ForegroundColor Green
} else {
    Write-Host "[2/3] 启动 DeepAnalyze 前端 (:$DA_FRONTEND_PORT)..." -ForegroundColor Cyan
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

# ---------- 3/3. Wren 查询服务 (9471) ----------
# 正常情况下 backend 在 lifespan 里会自动拉起 wren service。
# 这里作为兜底：等 backend 就绪 8 秒后若 9471 仍未起来，就显式拉 driver。
if (Test-Port $DA_WREN_PORT) {
    Write-Host "[3/3] Wren 查询服务已在运行 (:$DA_WREN_PORT)" -ForegroundColor Green
} else {
    Write-Host "[3/3] 等待 backend 拉起 Wren 查询服务 (:$DA_WREN_PORT)..." -ForegroundColor Cyan
    $ready = $false
    for ($i = 1; $i -le 10; $i++) {
        Start-Sleep -Seconds 2
        if (Test-Port $DA_WREN_PORT) { $ready = $true; break }
    }
    if (-not $ready) {
        Write-Host "      backend 未自动拉起 wren，显式启动 driver..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Force -Path "$DA_DIR\logs" | Out-Null
        Start-Process -FilePath $WREN_PY `
            -ArgumentList @($WREN_DRIVER, "--port", "$DA_WREN_PORT", "--token-file", $WREN_TOKEN) `
            -WorkingDirectory $DA_DIR -WindowStyle Hidden `
            -RedirectStandardOutput $WREN_LOG `
            -RedirectStandardError "$DA_DIR\logs\wren_service_err.log"
        for ($i = 1; $i -le 15; $i++) {
            Start-Sleep -Seconds 2
            if (Test-Port $DA_WREN_PORT) { $ready = $true; break }
        }
    }
    if ($ready) {
        Write-Host "      OK: http://localhost:$DA_WREN_PORT" -ForegroundColor Green
    } else {
        Write-Host "      失败，查看 $WREN_LOG" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  全部服务：" -ForegroundColor Cyan
Write-Host "   前端:      http://localhost:$DA_FRONTEND_PORT"
Write-Host "   后端 API:  http://localhost:$DA_BACKEND_PORT"
Write-Host "   Wren 查询: http://localhost:$DA_WREN_PORT"
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
