#!/bin/zsh
# 自動周回スーパーバイザ: autolive.py がクラッシュ/終了しても、目標時刻まで自動再起動する。
# 使い方: tools/supervise_autolive.sh <target_epoch>
# target_epoch: 終了する UNIX 時刻（秒）。これを過ぎたら再起動せず終了。
set -u
cd "$(dirname "$0")/.."
source .venv/bin/activate

TARGET="${1:?usage: supervise_autolive.sh <target_epoch>}"
LOG="/tmp/i7_autorun.log"
SUPLOG="/tmp/i7_supervisor.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$SUPLOG"; }

log "supervisor start (target=$(date -r "$TARGET" '+%Y-%m-%d %H:%M:%S'))"
attempt=0
while :; do
  now=$(date +%s)
  remain=$(( TARGET - now ))
  if (( remain <= 0 )); then
    log "target reached; stopping supervisor"
    break
  fi
  attempt=$(( attempt + 1 ))
  log "launch attempt #$attempt, remain=${remain}s"
  # -u でアンバッファ出力（クラッシュ時もログが残る）。stdout/stderr を時刻付きで追記。
  python -u tools/autolive.py --loops 99999 --max-seconds "$remain" --no-esc --flick >> "$LOG" 2>&1
  rc=$?
  log "autolive exited rc=$rc (attempt #$attempt)"
  # 正常な時間切れ終了か判定: 残り時間がほぼ無ければ終了
  now=$(date +%s)
  if (( TARGET - now <= 5 )); then
    log "no time remaining after exit; stopping"
    break
  fi
  # クラッシュ後はゲームが固まっている可能性。少し待って再起動（PAUSEは autolive 側が再開）
  log "restarting in 8s..."
  sleep 8
done
log "supervisor done"
