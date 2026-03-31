@echo off
title Tax Office AI - Server Start
color 0B

echo.
echo  ========================================
echo   Tax Office AI - Starting servers...
echo  ========================================
echo.

:: Move to project folder
cd /d "%~dp0"

:: Check .env file
if not exist backend\.env (
    echo  [ERROR] backend\.env not found.
    echo  Run install_from_github.bat first.
    pause
    exit /b 1
)

:: Check API key
set "has_key=0"
findstr /C:"GOOGLE_API_KEY=AI" backend\.env > nul 2>&1 && set "has_key=1"
findstr /C:"ANTHROPIC_API_KEY=sk-" backend\.env > nul 2>&1 && set "has_key=1"
if "%has_key%"=="0" (
    echo  [WARNING] API key not set.
    echo  Open backend\.env and set your API key.
    echo.
    echo  Open settings? (Y/N)
    set /p "yn="
    if /i "%yn%"=="Y" notepad backend\.env
    echo.
    echo  After setting API key, run this file again.
    pause
    exit /b 1
)

:: Stop existing processes
echo  Stopping existing servers...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 "') do (
    taskkill /f /pid %%a > nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5173 "') do (
    taskkill /f /pid %%a > nul 2>&1
)
timeout /t 1 /nobreak > nul

:: Start backend
echo  Starting backend server (port 8000)...
start "AI-Backend" /min cmd /k "cd /d %~dp0 && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

timeout /t 3 /nobreak > nul

:: Start frontend
echo  Starting frontend server (port 5173)...
start "AI-Frontend" /min cmd /k "cd /d %~dp0\frontend && python -m http.server 5173"

timeout /t 2 /nobreak > nul

:: Open browser
echo  Opening browser...
start http://localhost:5173

echo.
echo  ========================================
echo   Servers started!
echo  ========================================
echo.
echo  Dashboard: http://localhost:5173
echo  API docs:  http://localhost:8000/docs
echo.
echo  To stop: run stop_servers.bat
echo.
echo  You can close this window.
echo.
pause
