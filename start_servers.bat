@echo off
chcp 65001 > nul
title 税理士事務所AIシステム - サーバー起動
color 0B

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║  税理士事務所 AIエージェント管理システム             ║
echo  ║  サーバー起動中...                                   ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: プロジェクトフォルダに移動
cd /d "%~dp0"

:: .envファイル確認
if not exist backend\.env (
    echo  [エラー] backend\.env が見つかりません。
    echo  先に setup_windows.bat を実行してください。
    pause
    exit /b 1
)

:: APIキー確認（GOOGLE_API_KEYまたはANTHROPIC_API_KEY）
set "has_key=0"
findstr /C:"GOOGLE_API_KEY=AI" backend\.env > nul 2>&1 && set "has_key=1"
findstr /C:"ANTHROPIC_API_KEY=sk-" backend\.env > nul 2>&1 && set "has_key=1"
if "%has_key%"=="0" (
    echo  [警告] APIキーが設定されていません。
    echo  backend\.env をメモ帳で開いてAPIキーを設定してください。
    echo.
    echo  設定しますか？ (Y/N)
    set /p "yn="
    if /i "%yn%"=="Y" notepad backend\.env
    echo.
    echo  APIキー設定後、再度このファイルを実行してください。
    pause
    exit /b 1
)

:: 既存プロセスの停止
echo  既存のサーバーを停止しています...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 "') do (
    taskkill /f /pid %%a > nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5173 "') do (
    taskkill /f /pid %%a > nul 2>&1
)
timeout /t 1 /nobreak > nul

:: バックエンド起動
echo  バックエンドサーバーを起動しています（ポート8000）...
start "AI-Backend" /min cmd /k "chcp 65001 > nul && cd /d %~dp0 && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

timeout /t 3 /nobreak > nul

:: フロントエンド起動
echo  フロントエンドサーバーを起動しています（ポート5173）...
start "AI-Frontend" /min cmd /k "chcp 65001 > nul && cd /d %~dp0\frontend && python -m http.server 5173"

timeout /t 2 /nobreak > nul

:: ブラウザを自動で開く
echo  ブラウザを起動しています...
start http://localhost:5173

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║  サーバー起動完了！                                  ║
echo  ╠══════════════════════════════════════════════════════╣
echo  ║  ダッシュボード: http://localhost:5173               ║
echo  ║  API確認:        http://localhost:8000/docs          ║
echo  ╠══════════════════════════════════════════════════════╣
echo  ║  停止するには stop_servers.bat を実行してください    ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  この画面は閉じてOKです。
echo.
pause
