@echo off
setlocal

echo Stopping AI Chat System
echo =======================

for /f "delims=" %%a in ('python -c "from backend_app.settings import settings; print(settings.http_server_port)"') do set "FILE_SERVER_PORT=%%a"
for /f "delims=" %%a in ('python -c "from backend_app.settings import settings; print(settings.backend_port)"') do set "BACKEND_PORT=%%a"
for /f "delims=" %%a in ('python -c "from backend_app.settings import settings; print(settings.frontend_port)"') do set "FRONTEND_PORT=%%a"

echo Releasing ports...
call :KillPort %FILE_SERVER_PORT%
call :KillPort %BACKEND_PORT%
call :KillPort %FRONTEND_PORT%

echo.
echo Cleaning up remaining processes...
:: Kill by image name as a fallback
taskkill /F /IM "python.exe" /FI "WINDOWTITLE eq DeepAnalyze Backend*" >nul 2>&1
taskkill /F /IM "node.exe" >nul 2>&1
:: Note: Killing all node.exe might be aggressive if user has other node projects running.
:: But filtering by command line arguments is hard in batch.
:: The port killing above is the safest method. This is just cleanup.

echo.
echo System stopped successfully.
echo.
echo Log files are kept in the logs\ directory.
echo To restart the system: run start.bat
goto :eof

:KillPort
set port=%1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":"%port% ^| findstr "LISTENING"') do (
    echo   Releasing port %port% [PID: %%a]...
    taskkill /F /PID %%a >nul 2>&1
)
goto :eof
