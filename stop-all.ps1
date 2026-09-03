# 停止 DeepAnalyze + WrenAI 组合环境的全部服务
$ErrorActionPreference = "SilentlyContinue"

$ports = @(8765, 9000, 4000)
$names = @{ 8765 = "WrenAI MCP"; 9000 = "DeepAnalyze 后端"; 4000 = "DeepAnalyze 前端" }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  停止全部服务" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        $conns | ForEach-Object {
            Write-Host "  停止 $($names[$port]) (PID $($_.OwningProcess), 端口 $port)..." -ForegroundColor Yellow
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "  $($names[$port]) 未在运行" -ForegroundColor DarkGray
    }
}

# 前端是 node 子进程，兜底清理
Start-Sleep -Seconds 2
Get-Process -Name node -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and $_.Path -like "D:\DataAI\*"
} | ForEach-Object {
    Write-Host "  清理残留 node 进程 (PID $($_.Id))..." -ForegroundColor DarkGray
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "全部已停止。" -ForegroundColor Green
Write-Host ""
if ([Environment]::UserInteractive -and $Host.Name -eq "ConsoleHost") {
    Read-Host "按回车退出"
}
