#!/bin/zsh
# 朝の復旧watcher: ユーザーが iPhone を触った/再起動した合図を検知したら exit 0。
# 合図 = ミラーリングウィンドウ消失 / ウィンドウID変化 / 画面の大幅な暗転（切断オーバーレイ）。
# 入力は一切送らない（読むだけ）。
set -u
cd /Users/yo4raw/git/i7_autoplay
source .venv/bin/activate
BASE_ID="${1:?usage: i7_morning_watcher.sh <baseline_window_id>}"
echo "watcher start baseline_id=$BASE_ID"
while :; do
  sleep 60
  out=$(python - <<'EOF' 2>/dev/null
import sys; sys.path.insert(0, 'tools')
import driver
import numpy as np
try:
    w = driver.find_window()
    f = driver.grab(w)
    print(f"{w['win_id']} {float(np.mean(f)):.1f}")
except Exception:
    print("GONE 0")
EOF
)
  wid=${out%% *}
  bright=${out##* }
  ts=$(date '+%H:%M:%S')
  if [[ "$wid" == "GONE" ]]; then
    echo "[$ts] window gone -> trigger"; exit 0
  fi
  if [[ "$wid" != "$BASE_ID" ]]; then
    echo "[$ts] window id changed ($BASE_ID -> $wid) -> trigger"; exit 0
  fi
  if (( $(echo "$bright < 35" | bc -l) )); then
    echo "[$ts] screen went dark (mean=$bright, disconnect overlay?) -> trigger"; exit 0
  fi
done
