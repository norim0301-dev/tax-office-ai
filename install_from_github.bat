@echo off
chcp 65001 > nul
title 税理士事務所AIシステム - 自動インストール
color 0A

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║  税理士事務所 AIエージェント管理システム             ║
echo  ║  自動インストール                                    ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  このまま待つだけでインストールが完了します。
echo  途中で画面を閉じないでください。
echo.

:: ============================================================
:: 1. Git の確認・自動インストール
:: ============================================================
echo  [1/5] Gitを確認しています...
git --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  Gitが見つかりません。自動でダウンロード・インストールします。
    echo  少々お待ちください...
    echo.

    :: wingetで自動インストールを試みる
    winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements > nul 2>&1
    if errorlevel 1 (
        echo  自動インストールできませんでした。
        echo.
        echo  以下のURLをブラウザで開いてGitをインストールしてください:
        echo  https://git-scm.com/download/win
        echo.
        echo  設定は全て「Next」のままでOKです。
        echo  インストール後、このファイルを再度ダブルクリックしてください。
        echo.
        start https://git-scm.com/download/win
        pause
        exit /b 1
    )
    :: PATHを再読み込み
    set "PATH=%PATH%;C:\Program Files\Git\cmd"
    echo  Gitのインストールが完了しました。
) else (
    echo  OK
)
echo.

:: ============================================================
:: 2. Python の確認・自動インストール
:: ============================================================
echo  [2/5] Pythonを確認しています...
python --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  Pythonが見つかりません。自動でダウンロード・インストールします。
    echo  少々お待ちください...
    echo.

    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements > nul 2>&1
    if errorlevel 1 (
        echo  自動インストールできませんでした。
        echo.
        echo  以下のURLをブラウザで開いてPythonをインストールしてください:
        echo  https://www.python.org/downloads/
        echo.
        echo  ★重要★「Add Python to PATH」に必ずチェックを入れてください！
        echo.
        echo  インストール後、PCを再起動してからこのファイルを再度ダブルクリックしてください。
        echo.
        start https://www.python.org/downloads/
        pause
        exit /b 1
    )
    :: PATHを再読み込み
    set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts"
    echo  Pythonのインストールが完了しました。
) else (
    echo  OK
)
echo.

:: ============================================================
:: 3. プロジェクトをダウンロード
:: ============================================================
set "INSTALL_DIR=%USERPROFILE%\Documents\tax-office-ai"

echo  [3/5] AIシステムをダウンロードしています...
if exist "%INSTALL_DIR%" (
    echo  既にインストール済みです。最新版に更新します...
    cd /d "%INSTALL_DIR%"
    git pull origin main 2>nul
) else (
    git clone https://github.com/norim0301-dev/tax-office-ai.git "%INSTALL_DIR%" 2>nul
    if errorlevel 1 (
        echo.
        echo  [エラー] ダウンロードに失敗しました。
        echo  インターネット接続を確認して再度実行してください。
        pause
        exit /b 1
    )
    cd /d "%INSTALL_DIR%"
)
echo  OK
echo.

:: ============================================================
:: 4. ライブラリをインストール
:: ============================================================
echo  [4/5] 必要なライブラリをインストールしています...
echo  （初回は数分かかります。お待ちください...）
python -m pip install --upgrade pip --quiet 2>nul
python -m pip install -r backend\requirements.txt --quiet 2>nul
echo  OK
echo.

:: ============================================================
:: 5. 設定ファイルとショートカット作成
:: ============================================================
echo  [5/5] 初期設定をしています...

:: .env作成
if not exist backend\.env (
    copy backend\env_template backend\.env > nul 2>&1
    if not exist backend\.env (
        (
            echo ANTHROPIC_API_KEY=
            echo GOOGLE_API_KEY=
            echo GMAIL_ADDRESS=
            echo GMAIL_APP_PASSWORD=
        ) > backend\.env
    )
)

:: デスクトップにショートカット作成
(
    echo @echo off
    echo cd /d "%INSTALL_DIR%"
    echo call start_servers.bat
) > "%USERPROFILE%\Desktop\税理士AI起動.bat"

(
    echo @echo off
    echo cd /d "%INSTALL_DIR%"
    echo call update.bat
) > "%USERPROFILE%\Desktop\税理士AIアップデート.bat"

echo  OK
echo.

:: ============================================================
:: APIキー設定
:: ============================================================
echo  ╔══════════════════════════════════════════════════════╗
echo  ║  あと1つだけ設定が必要です！                         ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  今からメモ帳で設定ファイルを開きます。
echo.
echo  「GOOGLE_API_KEY=」の後に Gemini APIキーを貼り付けて
echo  Ctrl+S で保存してから、メモ帳を閉じてください。
echo.
echo  （APIキーは https://aistudio.google.com/apikey で無料取得できます）
echo.
pause

notepad backend\.env

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║                                                      ║
echo  ║   インストール完了！                                 ║
echo  ║                                                      ║
echo  ║   デスクトップに以下が作成されました:               ║
echo  ║     「税理士AI起動.bat」     → 起動                 ║
echo  ║     「税理士AIアップデート.bat」→ 最新版に更新      ║
echo  ║                                                      ║
echo  ║   今すぐ起動しますか？                              ║
echo  ║                                                      ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
set /p "yn=  起動する場合は Y を入力してEnter: "
if /i "%yn%"=="Y" (
    call start_servers.bat
)
echo.
pause
