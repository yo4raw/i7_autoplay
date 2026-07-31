#!/bin/zsh
# 自動周回スーパーバイザ: autolive.py がクラッシュ/終了しても、目標時刻まで自動再起動する。
# 使い方: tools/ops/supervise_autolive.sh <target_epoch>
# target_epoch: 終了する UNIX 時刻（秒）。これを過ぎたら再起動せず終了。
set -u
cd "$(dirname "$0")/../.."
source .venv/bin/activate

TARGET="${1:?usage: supervise_autolive.sh <target_epoch>}"
LOG="/tmp/i7_autorun.log"
SUPLOG="/tmp/i7_supervisor.log"
# 打鍵オプション。実機検証で確定した値を既定にする（2026-07-31）:
#   --auto-circles : 機種差の円ズレを自動補正。これが無いと MISS 51・グレードB になる
#                    （補正値は .autocal_circles.json にキャッシュされ再起動時に即復元）
#   --note-lead 0.04 : 早撃ち量の実測最適値（0.025→P14/GOOD70、0.04→P33、0.055→P22）
#   --flick        : 赤ノーツのフリック（既存）
# 上書きしたいときは I7_TAP_OPTS 環境変数で丸ごと差し替える。
TAP_OPTS="${I7_TAP_OPTS:---flick --auto-circles --note-lead 0.04}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$SUPLOG"; }

log "supervisor start (target=$(date -r "$TARGET" '+%Y-%m-%d %H:%M:%S')) opts=[$TAP_OPTS]"
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
  python -u tools/autolive.py --loops 99999 --max-seconds "$remain" --no-esc ${=TAP_OPTS} >> "$LOG" 2>&1
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
