@echo off
chcp 65001 > nul
title 税理士事務所AIシステム - サーバー停止

echo ============================================================
echo  税理士事務所 AIエージェント管理システム - サーバー停止
echo ============================================================
echo.

echo ポート8000（バックエンド）を停止しています...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 "') do (
    taskkill /f /pid %%a > nul 2>&1
)

echo ポート5173（フロントエンド）を停止しています...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173 "') do (
    taskkill /f /pid %%a > nul 2>&1
)

echo.
echo サーバーを停止しました。
echo.
pause
