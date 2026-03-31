#!/bin/bash
# Windows転送用ZIPパッケージを作成するスクリプト（Mac上で実行）

cd "/Users/nori/Desktop/税理士事務所　組織構築案"

echo "Windows用パッケージを作成しています..."

# 一時的に .env をコピー（中身は空に）
cp backend/.env backend/.env.bak 2>/dev/null || true
echo "ANTHROPIC_API_KEY=ここにAPIキーを貼り付けてください" > backend/.env_windows_template

# ZIPを作成（除外ファイルあり）
zip -r "Windows転送用_AIシステム.zip" \
    backend/ \
    frontend/ \
    setup_windows.bat \
    start_servers.bat \
    stop_servers.bat \
    -x "backend/.env" \
    -x "backend/__pycache__/*" \
    -x "backend/agents/__pycache__/*" \
    -x "*.pyc" \
    -x "*.DS_Store" \
    -x ".env.bak"

# テンプレートの.envをZIPに追加（空のAPIキー状態）
zip "Windows転送用_AIシステム.zip" backend/.env_windows_template
# ZIPの中でリネーム（注意: zipコマンドではできないので手動で説明）

# クリーンアップ
rm -f backend/.env_windows_template
mv backend/.env.bak backend/.env 2>/dev/null || true

echo ""
echo "完了! 「Windows転送用_AIシステム.zip」を作成しました。"
echo "このZIPをWindowsのUSBメモリまたはメール添付でコピーしてください。"
ls -lh "Windows転送用_AIシステム.zip"
