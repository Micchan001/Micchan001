#!/bin/bash
# AI秘書を実行するスクリプト

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 環境変数の読み込み
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Python仮想環境のアクティベート（存在する場合）
if [ -d .venv ]; then
    source .venv/bin/activate
elif [ -d venv ]; then
    source venv/bin/activate
fi

# 引数の処理
INTERVAL=${SECRETARY_INTERVAL:-60}
MODE="loop"

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --once) MODE="once" ;;
        --interval) INTERVAL="$2"; shift ;;
        *) echo "不明な引数: $1"; exit 1 ;;
    esac
    shift
done

echo "AI秘書を起動します..."

if [ "$MODE" = "once" ]; then
    python -m secretary.scheduler --once
else
    python -m secretary.scheduler --interval "$INTERVAL"
fi
