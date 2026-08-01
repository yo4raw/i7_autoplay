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
#   （--note-lead は指定しない: 打鍵ループ高速化で最適値が変わったため autolive の既定に従う）
#   --flick        : 赤ノーツのフリック（既存）
# 上書きしたいときは I7_TAP_OPTS 環境変数で丸ごと差し替える。
TAP_OPTS="${I7_TAP_OPTS:---flick --auto-circles --note-lead 0.02}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$SUPLOG"; }

log "supervisor start (target=$(date -r "$TARGET" '+%Y-%m-%d %H:%M:%S')) opts=[$TAP_OPTS]"
attempt=0
last_clears=$(grep -c "ライブ クリア" "$LOG" 2>/dev/null | head -1)
barren=0
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
  # rc=42 は autolive の**安全停止**（未知画面・きなこパン枯渇・切断など）。
  # 人間の確認が必要で、再起動しても同じ画面で止まるだけなので supervisor ごと終了する。
  # 従来は rc を見ずに8秒後へ再起動し、26〜36秒周期の空転を延々と繰り返していた
  # （実測 2026-08-01: 12連続、ログ全体で「完了: 0 回クリア」71件）。
  if (( rc == 42 )); then
    log "safety stop (rc=42); NOT restarting. 直近のスクショ: /tmp/i7dbg/"
    touch "${I7_SAFE_FLAG:-/tmp/i7_safe_stop_fired}"
    break
  fi
  # 正常な時間切れ終了か判定: 残り時間がほぼ無ければ終了
  now=$(date +%s)
  if (( TARGET - now <= 5 )); then
    log "no time remaining after exit; stopping"
    break
  fi
  # 進捗（クリア）が増えないまま終了が続くなら、再起動しても無駄なので諦める。
  clears=$(grep -c "ライブ クリア" "$LOG" 2>/dev/null | head -1)
  if (( clears > last_clears )); then
    last_clears=$clears; barren=0
  else
    barren=$(( barren + 1 ))
    if (( barren >= 4 )); then
      log "4回連続でクリアが増えないまま終了 → 空転とみなし停止する"
      touch "${I7_BARREN_FLAG:-/tmp/i7_barren_fired}"
      break
    fi
  fi
  # クラッシュ後はゲームが固まっている可能性。待ってから再起動（PAUSEは autolive 側が再開）。
  # 空転が続くほど待ちを伸ばす（8→16→32→64…上限300秒）。
  wait=$(( 8 * (1 << barren) )); (( wait > 300 )) && wait=300
  log "restarting in ${wait}s... (barren=$barren)"
  sleep "$wait"
done
log "supervisor done"
