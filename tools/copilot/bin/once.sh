#!/bin/zsh
# pi-durable コパイロットの1サイクル動作確認。会話を1回だけ動かして終了する。
# 実モデルを使うには ANTHROPIC_API_KEY が必要。オフライン疎通は --faux。
#
# 使い方:
#   tools/copilot/bin/once.sh [model] [--faux] [--db path]
#   tools/copilot/bin/once.sh --faux          # モデル省略時は既定値
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")/.."

MODEL="${I7_COPILOT_MODEL:-anthropic/claude-sonnet-4-6}"
if [[ -n "${1:-}" && "${1:0:1}" != "-" ]]; then
  MODEL="$1"; shift
fi

if [[ ! -d node_modules ]]; then
  echo "node_modules がありません。先に実行: cd tools/copilot && npm install" >&2
  exit 2
fi

exec node src/supervisor.mjs once --model "$MODEL" "$@"
