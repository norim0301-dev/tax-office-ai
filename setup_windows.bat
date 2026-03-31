@echo off
chcp 65001 > nul
title 税理士事務所AIシステム - セットアップ
color 0A

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║  税理士事務所 AIエージェント管理システム             ║
echo  ║  Windows セットアップ                                ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: Pythonのバージョン確認
echo  [1/5] Pythonのバージョンを確認しています...
python --version 2>nul
if errorlevel 1 (
    echo.
    echo  ╔══════════════════════════════════════════════════════╗
    echo  ║  [エラー] Pythonが見つかりません                     ║
    echo  ╚══════════════════════════════════════════════════════╝
    echo.
    echo  以下のURLからPython 3.11以上をインストールしてください:
    echo  https://www.python.org/downloads/
    echo.
    echo  ★重要★ インストール画面の最初で
    echo  「Add Python to PATH」に必ずチェックを入れてください！
    echo.
    echo  インストール後、PCを再起動してからこのファイルを再実行してください。
    echo.
    pause
    exit /b 1
)
echo  OK
echo.

:: Node.jsの確認（任意）
echo  [2/5] Node.jsを確認しています...
node --version 2>nul
if errorlevel 1 (
    echo  Node.jsは未インストールです（Python版フロントエンドを使用します）
) else (
    echo  OK
)
echo.

:: pipのアップグレード
echo  [3/5] pipを最新版にアップグレードしています...
python -m pip install --upgrade pip --quiet 2>nul
echo  OK
echo.

:: ライブラリのインストール
echo  [4/5] 必要なライブラリをインストールしています...
echo  （初回は数分かかります。お待ちください...）
echo.
python -m pip install -r backend\requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo  [エラー] ライブラリのインストールに失敗しました。
    echo  インターネット接続を確認してから再度実行してください。
    pause
    exit /b 1
)
echo  OK
echo.

:: .envファイルの確認・作成
echo  [5/5] 設定ファイルを確認しています...
if not exist backend\.env (
    (
        echo ANTHROPIC_API_KEY=ここにAPIキーを貼り付けてください
        echo GOOGLE_API_KEY=
        echo.
        echo # Gmail連携（秘書AI メール機能用）
        echo GMAIL_ADDRESS=
        echo GMAIL_APP_PASSWORD=
    ) > backend\.env
    echo.
    echo  ╔══════════════════════════════════════════════════════╗
    echo  ║  [重要] backend\.env ファイルを作成しました         ║
    echo  ╚══════════════════════════════════════════════════════╝
    echo.
    echo  メモ帳で backend\.env を開き、APIキーを設定してください:
    echo.
    echo  ・GOOGLE_API_KEY = Gemini APIキー（無料推奨）
    echo    取得先: https://aistudio.google.com/apikey
    echo.
    echo  ・ANTHROPIC_API_KEY = Claude APIキー（有料）
    echo    取得先: https://console.anthropic.com/
    echo.
    echo  ※ どちらか1つだけでOKです（Gemini推奨）
    echo.
    notepad backend\.env
) else (
    echo  backend\.env ファイルが存在します。
    findstr /C:"ここにAPIキー" backend\.env > nul
    if not errorlevel 1 (
        echo.
        echo  [警告] APIキーがまだ設定されていません。
        echo  メモ帳で設定画面を開きます...
        notepad backend\.env
    ) else (
        echo  APIキーが設定済みです。
    )
)
echo.

echo  ╔══════════════════════════════════════════════════════╗
echo  ║  セットアップ完了！                                  ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  次のステップ:
echo   1. backend\.env のAPIキーを設定（まだの場合）
echo   2. start_servers.bat をダブルクリックでサーバー起動
echo   3. ブラウザで http://localhost:5173 が自動で開きます
echo.
echo  ※ 困ったときは「Windows起動手順.txt」を参照してください
echo.
pause
