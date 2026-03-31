@echo off
chcp 65001 > nul
title 税理士事務所AIシステム - アップデート
color 0E

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║  税理士事務所 AIエージェント管理システム             ║
echo  ║  最新版にアップデート                                ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: Git確認
git --version > nul 2>&1
if errorlevel 1 (
    echo  [エラー] Gitがインストールされていません。
    echo  https://git-scm.com/download/win からインストールしてください。
    echo  インストール時はデフォルト設定のままでOKです。
    pause
    exit /b 1
)

:: サーバー停止
echo  サーバーを停止しています...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 "') do (
    taskkill /f /pid %%a > nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5173 "') do (
    taskkill /f /pid %%a > nul 2>&1
)
timeout /t 1 /nobreak > nul

:: 最新版を取得
echo  GitHubから最新版を取得しています...
git pull origin main
if errorlevel 1 (
    echo.
    echo  [エラー] アップデートに失敗しました。
    echo  ローカルの変更がある場合は以下を実行してください:
    echo    git stash
    echo    git pull origin main
    echo    git stash pop
    pause
    exit /b 1
)

:: ライブラリ更新
echo.
echo  ライブラリを更新しています...
python -m pip install -r backend\requirements.txt --quiet 2>nul

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║  アップデート完了！                                  ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  start_servers.bat でサーバーを起動してください。
echo.
pause
