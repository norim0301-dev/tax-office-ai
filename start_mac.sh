#!/bin/bash
# 税理士事務所AIエージェントシステム - Mac自動起動スクリプト

PROJECT_DIR="/Users/nori/Desktop/税理士事務所　組織構築案"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

# 既に起動しているか確認
if lsof -i :8000 -t > /dev/null 2>&1; then
    echo "バックエンドは既に起動中です (ポート8000)"
else
    echo "バックエンドを起動中..."
    cd "$PROJECT_DIR/backend"
    /usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 > "$LOG_DIR/backend.log" 2>&1 &
    echo "バックエンド起動完了 (PID: $!)"
fi

if lsof -i :5173 -t > /dev/null 2>&1; then
    echo "フロントエンドは既に起動中です (ポート5173)"
else
    echo "フロントエンドを起動中..."
    cd "$PROJECT_DIR/frontend"
    /usr/local/bin/npx vite --host 0.0.0.0 --port 5173 > "$LOG_DIR/frontend.log" 2>&1 &
    echo "フロントエンド起動完了 (PID: $!)"
fi

# サーバー起動を待ってからブラウザを開く
sleep 3
open http://localhost:5173
