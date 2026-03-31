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
where git > nul 2>&1
if errorlevel 1 (
    echo.
    echo  Gitが見つかりません。自動でダウンロード・インストールします。
    echo  少々お待ちください（数分かかります）...
    echo.

    :: wingetで自動インストールを試みる
    where winget > nul 2>&1
    if errorlevel 1 (
        echo  wingetが利用できません。
        echo  以下のURLをブラウザで開いてGitをインストールしてください:
        echo  https://git-scm.com/download/win
        echo.
        echo  設定は全て「Next」のままでOKです。
        echo  インストール後、このファイルを再度ダブルクリックしてください。
        start https://git-scm.com/download/win
        pause
        exit /b 1
    )
    echo  wingetでGitをインストール中...
    winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
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
    for /f "tokens=*" %%v in ('git --version 2^>nul') do echo  %%v
    echo  OK
)
echo.

:: ============================================================
:: 2. Python の確認・自動インストール
:: ============================================================
echo  [2/5] Pythonを確認しています...
where python > nul 2>&1
if errorlevel 1 (
    echo.
    echo  Pythonが見つかりません。自動でダウンロード・インストールします。
    echo  少々お待ちください（数分かかります）...
    echo.

    where winget > nul 2>&1
    if errorlevel 1 (
        echo  wingetが利用できません。
        echo  以下のURLをブラウザで開いてPythonをインストールしてください:
        echo  https://www.python.org/downloads/
        echo  ★重要★「Add Python to PATH」に必ずチェックを入れてください！
        start https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo  wingetでPythonをインストール中...
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
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
    for /f "tokens=*" %%v in ('python --version 2^>nul') do echo  %%v
    echo  OK
)
echo.

:: ============================================================
:: 3. プロジェクトをダウンロード
:: ============================================================
set "INSTALL_DIR=%USERPROFILE%\Documents\tax-office-ai"

echo  [3/5] AIシステムをダウンロードしています...
echo  保存先: %INSTALL_DIR%
if exist "%INSTALL_DIR%" (
    echo  既にインストール済みです。最新版に更新します...
    cd /d "%INSTALL_DIR%"
    git pull origin main
    if errorlevel 1 (
        echo  更新に失敗しました。再クローンします...
        cd /d "%USERPROFILE%\Documents"
        rmdir /s /q "%INSTALL_DIR%" 2>nul
        git clone https://github.com/norim0301-dev/tax-office-ai.git "%INSTALL_DIR%"
        if errorlevel 1 (
            echo.
            echo  [エラー] ダウンロードに失敗しました。
            echo  エラー内容を確認してください。
            pause
            exit /b 1
        )
    )
) else (
    echo  GitHubからダウンロード中...
    git clone https://github.com/norim0301-dev/tax-office-ai.git "%INSTALL_DIR%"
    if errorlevel 1 (
        echo.
        echo  [エラー] ダウンロードに失敗しました。
        echo  インターネット接続を確認して再度実行してください。
        pause
        exit /b 1
    )
)
cd /d "%INSTALL_DIR%"
echo  OK
echo.

:: ============================================================
:: 4. ライブラリをインストール
:: ============================================================
echo  [4/5] 必要なライブラリをインストールしています...
echo  （初回は数分かかります。お待ちください...）
python -m pip install --upgrade pip 2>&1
if errorlevel 1 (
    echo  [警告] pipの更新に失敗しましたが、続行します...
)
python -m pip install -r "%INSTALL_DIR%\backend\requirements.txt" 2>&1
if errorlevel 1 (
    echo  [警告] 一部のライブラリのインストールに失敗しましたが、続行します...
)
echo  OK
echo.

:: ============================================================
:: 5. 設定ファイルとショートカット作成
:: ============================================================
echo  [5/5] 初期設定をしています...

:: .env作成
if not exist "%INSTALL_DIR%\backend\.env" (
    echo  .envファイルを作成しています...
    if exist "%INSTALL_DIR%\backend\env_template" (
        copy "%INSTALL_DIR%\backend\env_template" "%INSTALL_DIR%\backend\.env" > nul 2>&1
    )
    if not exist "%INSTALL_DIR%\backend\.env" (
        echo  テンプレートからのコピーに失敗。直接作成します...
        (
            echo ANTHROPIC_API_KEY=
            echo GOOGLE_API_KEY=
            echo GMAIL_ADDRESS=
            echo GMAIL_APP_PASSWORD=
        ) > "%INSTALL_DIR%\backend\.env"
    )
    echo  .envファイル作成完了
) else (
    echo  .envファイルは既に存在します
)

:: デスクトップにショートカット作成
echo  デスクトップにショートカットを作成しています...

echo @echo off> "%USERPROFILE%\Desktop\税理士AI起動.bat"
echo cd /d "%INSTALL_DIR%">> "%USERPROFILE%\Desktop\税理士AI起動.bat"
echo call start_servers.bat>> "%USERPROFILE%\Desktop\税理士AI起動.bat"

echo @echo off> "%USERPROFILE%\Desktop\税理士AIアップデート.bat"
echo cd /d "%INSTALL_DIR%">> "%USERPROFILE%\Desktop\税理士AIアップデート.bat"
echo call update.bat>> "%USERPROFILE%\Desktop\税理士AIアップデート.bat"

if exist "%USERPROFILE%\Desktop\税理士AI起動.bat" (
    echo  「税理士AI起動.bat」作成OK
) else (
    echo  [エラー] 税理士AI起動.bat の作成に失敗しました
)
if exist "%USERPROFILE%\Desktop\税理士AIアップデート.bat" (
    echo  「税理士AIアップデート.bat」作成OK
) else (
    echo  [エラー] 税理士AIアップデート.bat の作成に失敗しました
)

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
echo  何かキーを押すとメモ帳が開きます...
pause > nul

:: 絶対パスでメモ帳を開く
if exist "%INSTALL_DIR%\backend\.env" (
    echo  メモ帳を開いています...
    notepad "%INSTALL_DIR%\backend\.env"
) else (
    echo  [エラー] 設定ファイルが見つかりません: %INSTALL_DIR%\backend\.env
    echo  手動で作成します...
    (
        echo ANTHROPIC_API_KEY=
        echo GOOGLE_API_KEY=
        echo GMAIL_ADDRESS=
        echo GMAIL_APP_PASSWORD=
    ) > "%INSTALL_DIR%\backend\.env"
    notepad "%INSTALL_DIR%\backend\.env"
)

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
    cd /d "%INSTALL_DIR%"
    call start_servers.bat
)
echo.
pause
