#!/bin/zsh
# 指定時刻まで周回し続ける。**ミラーリング切断中は supervisor を回さずに待つ**。
#
# supervisor は autolive が落ちると 8 秒後に再起動するが、切断中は毎回「未知画面に
# 25s 停滞 → 安全停止」で終わるため、26 秒ごとの無駄な再起動を延々と繰り返してしまう
# （実測 2026-08-01: attempt #7 まで空回り）。切断は人間が iPhone をロックするまで
# 復旧しないので、接続が戻るまでは何もせず待つのが正しい。
#
# 使い方: tools/ops/run_until.sh <target_epoch>
set -u
cd "$(dirname "$0")/../.."
TARGET="${1:?usage: run_until.sh <target_epoch>}"
LOG="/tmp/i7_runner.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# ミラーリングが繋がっていてゲーム画面が見えているか（切断画面なら false）
connected() {
  .venv/bin/python - <<'PY' 2>/dev/null
import sys
sys.path.insert(0, "tools")
try:
    import driver, autolive
    win = driver.find_window()
    # 切断中は縦長のダイアログ（幅 < 高さ）。ゲームは横向き。
    if win["w"] < win["h"]:
        sys.exit(1)
    al = autolive.AutoLive.__new__(autolive.AutoLive)
    al.templates = autolive.load_templates()
    al.win = win
    al.content = (38, int(win["h"]) - 9)
    al.verbose = False
    al._last_dark_check = 0.0
    state, _ = al.detect(driver.grab(win))
    sys.exit(0 if state != "menu" else 1)
except Exception:
    sys.exit(1)
PY
}

log "runner start (target=$(date -r "$TARGET" '+%Y-%m-%d %H:%M:%S'))"
waiting=0
while :; do
  now=$(date +%s)
  remain=$(( TARGET - now ))
  (( remain <= 0 )) && { log "target reached; done"; break; }

  if connected; then
    (( waiting )) && log "接続を確認 → 周回を再開"
    waiting=0
    log "supervisor 起動（残り ${remain}s）"
    tools/ops/supervise_autolive.sh "$TARGET"
    log "supervisor 終了"
  else
    if (( waiting == 0 )); then
      log "ミラーリング切断中（iPhone をロックすると自動再接続）。復帰まで待機する"
      waiting=1
    fi
    sleep 30
  fi
done
log "runner done"
