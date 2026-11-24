#!/bin/zsh
# pi-durable コパイロットの常駐起動。supervise_autolive.sh / run_until.sh と並走させる。
#
# 使い方:
#   tools/copilot/bin/watch.sh <target_epoch> [interval_sec] [model]
# 例:
#   tools/copilot/bin/watch.sh $(( $(date +%s) + 7200 )) 600 anthropic/claude-sonnet-4-6
#
# 再起動は人間が行う（プロセスが死んだら同じコマンドを再実行。durable task が途中から再開する）。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")/.."

TARGET="${1:?usage: watch.sh <target_epoch> [interval_sec] [model]}"
INTERVAL="${2:-${I7_COPILOT_INTERVAL:-600}}"
MODEL="${3:-${I7_COPILOT_MODEL:-anthropic/claude-sonnet-4-6}}"

if [[ ! -d node_modules ]]; then
  echo "node_modules がありません。先に実行:" >&2
  echo "  cd tools/copilot && npm install" >&2
  exit 2
fi

exec node src/supervisor.mjs watch --target "$TARGET" --interval "$INTERVAL" --model "$MODEL"
