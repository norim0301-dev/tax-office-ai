@echo off
chcp 65001 > nul
title 税理士事務所AIシステム - GitHub から初回インストール
color 0A

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║  税理士事務所 AIエージェント管理システム             ║
echo  ║  GitHub からインストール                             ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: Git確認
git --version > nul 2>&1
if errorlevel 1 (
    echo  [エラー] Gitがインストールされていません。
    echo.
    echo  先に以下をインストールしてください（すべてデフォルト設定でOK）:
    echo    1. Git:    https://git-scm.com/download/win
    echo    2. Python: https://www.python.org/downloads/
    echo       ★ 「Add Python to PATH」に必ずチェック！
    echo.
    echo  インストール後、PCを再起動してからこのファイルを再実行してください。
    pause
    exit /b 1
)

:: Python確認
python --version > nul 2>&1
if errorlevel 1 (
    echo  [エラー] Pythonがインストールされていません。
    echo  https://www.python.org/downloads/ からインストールしてください。
    echo  ★ 「Add Python to PATH」に必ずチェック！
    pause
    exit /b 1
)

:: インストール先を選択
set "INSTALL_DIR=%USERPROFILE%\Documents\tax-office-ai"
echo  インストール先: %INSTALL_DIR%
echo.

:: Clone
if exist "%INSTALL_DIR%" (
    echo  既にインストール済みです。アップデートを実行します...
    cd /d "%INSTALL_DIR%"
    git pull origin main
) else (
    echo  GitHubからダウンロードしています...
    git clone https://github.com/norim0301-dev/tax-office-ai.git "%INSTALL_DIR%"
    if errorlevel 1 (
        echo  [エラー] ダウンロードに失敗しました。
        echo  インターネット接続を確認してください。
        pause
        exit /b 1
    )
    cd /d "%INSTALL_DIR%"
)

:: ライブラリインストール
echo.
echo  必要なライブラリをインストールしています...
python -m pip install --upgrade pip --quiet 2>nul
python -m pip install -r backend\requirements.txt --quiet
echo  OK
echo.

:: .env作成
if not exist backend\.env (
    copy backend\env_template backend\.env > nul
    echo  ╔══════════════════════════════════════════════════════╗
    echo  ║  APIキーの設定が必要です                             ║
    echo  ╚══════════════════════════════════════════════════════╝
    echo.
    echo  メモ帳で設定ファイルを開きます。
    echo  GOOGLE_API_KEY= の後にGemini APIキーを貼り付けてください。
    echo  （https://aistudio.google.com/apikey で無料取得できます）
    echo.
    notepad backend\.env
)

:: デスクトップにショートカット作成
echo  デスクトップにショートカットを作成しています...
(
    echo @echo off
    echo cd /d "%INSTALL_DIR%"
    echo start_servers.bat
) > "%USERPROFILE%\Desktop\税理士AI起動.bat"

(
    echo @echo off
    echo cd /d "%INSTALL_DIR%"
    echo update.bat
) > "%USERPROFILE%\Desktop\税理士AIアップデート.bat"

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║  インストール完了！                                  ║
echo  ╠══════════════════════════════════════════════════════╣
echo  ║  デスクトップに以下が作成されました:                ║
echo  ║    ・税理士AI起動.bat       → サーバー起動          ║
echo  ║    ・税理士AIアップデート.bat → 最新版に更新        ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  「税理士AI起動.bat」をダブルクリックで起動できます。
echo.
pause
