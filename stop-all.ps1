# 停止 DeepAnalyze 环境的全部服务
$ErrorActionPreference = "SilentlyContinue"

$ports = @(9000, 4000, 9471)
$names = @{ 9000 = "DeepAnalyze 后端"; 4000 = "DeepAnalyze 前端"; 9471 = "Wren 查询服务" }

# 获取监听端口的进程 PID；Get-NetTCPConnection 失败时回退 netstat 解析
function Get-PortOwnerPids($port) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        return @($conns | ForEach-Object { $_.OwningProcess } | Select-Object -Unique)
    }
    $pids = @()
    foreach ($line in (netstat -ano)) {
        if ($line -match "^\s*TCP\s+\S+:$port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            $pids += [int]$Matches[1]
        }
    }
    return @($pids | Select-Object -Unique)
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  停止全部服务" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

foreach ($port in $ports) {
    $pids = Get-PortOwnerPids $port
    if ($pids.Count -gt 0) {
        foreach ($procId in $pids) {
            Write-Host "  停止 $($names[$port]) (PID $procId, 端口 $port)..." -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
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
