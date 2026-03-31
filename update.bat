@echo off
title Tax Office AI - Update
color 0E

echo.
echo  ========================================
echo   Tax Office AI - Updating to latest
echo  ========================================
echo.

cd /d "%~dp0"

:: Check Git
git --version > nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Git is not installed.
    echo  Install from: https://git-scm.com/download/win
    pause
    exit /b 1
)

:: Stop servers
echo  Stopping servers...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 "') do (
    taskkill /f /pid %%a > nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5173 "') do (
    taskkill /f /pid %%a > nul 2>&1
)
timeout /t 1 /nobreak > nul

:: Pull latest
echo  Downloading latest version from GitHub...
git pull origin main
if errorlevel 1 (
    echo.
    echo  [ERROR] Update failed.
    echo  If you have local changes, run:
    echo    git stash
    echo    git pull origin main
    echo    git stash pop
    pause
    exit /b 1
)

:: Update libraries
echo.
echo  Updating libraries...
python -m pip install -r backend\requirements.txt --quiet 2>nul

echo.
echo  ========================================
echo   Update complete!
echo  ========================================
echo.
echo  Run start_servers.bat to start.
echo.
pause
