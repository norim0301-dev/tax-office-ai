@echo off
title Tax Office AI - Server Stop

echo ========================================
echo  Tax Office AI - Stopping servers
echo ========================================
echo.

echo Stopping port 8000 (backend)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 "') do (
    taskkill /f /pid %%a > nul 2>&1
)

echo Stopping port 5173 (frontend)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173 "') do (
    taskkill /f /pid %%a > nul 2>&1
)

echo.
echo Servers stopped.
echo.
pause
