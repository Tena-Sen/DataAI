@echo off
setlocal
set PYTHONIOENCODING=utf-8

echo Starting Chat System
echo ==========================

:: Ensure logs directory exists
if not exist logs mkdir logs

:: Resolve ports through the same .env loader used by the backend.
for /f "delims=" %%a in ('python -c "from backend_app.settings import settings; print(settings.http_server_port)"') do set "FILE_SERVER_PORT=%%a"
for /f "delims=" %%a in ('python -c "from backend_app.settings import settings; print(settings.backend_port)"') do set "BACKEND_PORT=%%a"
for /f "delims=" %%a in ('python -c "from backend_app.settings import settings; print(settings.frontend_port)"') do set "FRONTEND_PORT=%%a"
if not defined NEXT_PUBLIC_BACKEND_URL set "NEXT_PUBLIC_BACKEND_URL=http://localhost:%BACKEND_PORT%"

:: Check and kill ports
call :KillPort %FILE_SERVER_PORT%
call :KillPort %BACKEND_PORT%
call :KillPort %FRONTEND_PORT%

echo Cleaning old processes...
:: Use wmic to kill process by command line pattern if needed, but port killing is usually sufficient.
:: Or explicitly kill python/node if they are hanging without ports (less reliable on Windows without precise pid tracking)

echo Cleanup completed.
echo.

:: Start backend API
echo Starting backend API...
start /B "DeepAnalyze Backend" cmd /c "python backend.py > logs\backend.log 2>&1"
:: Windows doesn't easily give us the PID of the started background process without external tools or complex PowerShell.
:: We will rely on port checking or tasklist if needed, but for now simple start is fine.
echo Backend started in background.
echo API running on: http://localhost:%BACKEND_PORT%
echo File service running on: http://localhost:%FILE_SERVER_PORT%

:: Wait for backend to initialize
timeout /t 3 /nobreak >nul

:: Start frontend
echo.
echo Starting React frontend...
cd frontend
start /B "DeepAnalyze Frontend" cmd /c "npm run dev -- -p %FRONTEND_PORT% > ..\logs\frontend.log 2>&1"
cd ..
echo Frontend started in background.
echo Frontend running on: http://localhost:%FRONTEND_PORT%

echo.
echo All services started successfully.
echo.
echo Service URLs:
echo   Backend API:  http://localhost:%BACKEND_PORT%
echo   Frontend:     http://localhost:%FRONTEND_PORT%
echo   File Service: http://localhost:%FILE_SERVER_PORT%
echo.
echo Log files:
echo   Backend: logs\backend.log
echo   Frontend: logs\frontend.log
echo.
echo Stop services: run stop.bat
goto :eof

:KillPort
set port=%1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":"%port% ^| findstr "LISTENING"') do (
    echo Port %port% is in use by PID %%a. Killing...
    taskkill /F /PID %%a >nul 2>&1
)
goto :eof
