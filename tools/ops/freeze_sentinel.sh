#!/bin/zsh
# フリーズ・センチネル: autolive ログを監視し、ゲームのハング兆候を検知したら
# recover_freeze.py で全自動復旧（強制終了→再起動→楽曲選択）し supervisor を再開する。
# 検知条件:
#   A) cardx停滞 warn が前回チェックから2回以上増加（「ライフを全回復しました」フリーズ等）
#   B) supervisor の launch attempt が4回以上増加したのに クリア数が増えていない（一般的な膠着）
# 使い方: tools/ops/freeze_sentinel.sh <target_epoch>
set -u
cd "$(dirname "$0")/../.."
source .venv/bin/activate
TARGET="${1:?usage: freeze_sentinel.sh <target_epoch>}"
LOG="/tmp/i7_autorun.log"
SUPLOG="/tmp/i7_supervisor.log"
SLOG="/tmp/i7_sentinel.log"
MAX_RECOVERIES=6
slog() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$SLOG"; }

# ベースカウンタは「進捗（クリア増）があった時」または「復旧後」にだけリセットする。
# （前版は毎ループ更新で、35秒/回の停止サイクルでは 45秒窓に閾値分の増加が乗らず永久に発火しなかった）
base_warn=$(grep -c "閉じられず停滞" "$LOG" 2>/dev/null || echo 0)
base_att=$(grep -c "launch attempt" "$SUPLOG" 2>/dev/null || echo 0)
base_clear=$(grep -c "ライブ クリア" "$LOG" 2>/dev/null || echo 0)
recoveries=0
slog "sentinel start (warn=$base_warn att=$base_att clear=$base_clear)"

while :; do
  sleep 45
  now=$(date +%s)
  if (( TARGET - now <= 0 )); then slog "target reached; exit"; exit 0; fi
  w=$(grep -c "閉じられず停滞" "$LOG" 2>/dev/null || echo 0)
  a=$(grep -c "launch attempt" "$SUPLOG" 2>/dev/null || echo 0)
  c=$(grep -c "ライブ クリア" "$LOG" 2>/dev/null || echo 0)
  if (( c > base_clear )); then
    # 進捗あり＝健全。ベースを現在値に合わせる。
    base_warn=$w; base_att=$a; base_clear=$c
    continue
  fi
  trigger=""
  if (( w - base_warn >= 2 )); then trigger="cardx_stuck x$((w - base_warn))"; fi
  if (( a - base_att >= 4 )); then trigger="${trigger} restart_loop x$((a - base_att))"; fi
  [[ -z "$trigger" ]] && continue

  recoveries=$(( recoveries + 1 ))
  slog "FREEZE detected ($trigger) -> recovery #$recoveries"
  if (( recoveries > MAX_RECOVERIES )); then
    slog "max recoveries exceeded; giving up"; touch /tmp/i7_freeze_unrecovered; exit 1
  fi
  pkill -f supervise_autolive.sh; pkill -f "autolive.py"; sleep 2
  if python -u tools/ops/recover_freeze.py >> "$SLOG" 2>&1; then
    slog "recovery OK -> relaunch supervisor"
    nohup tools/ops/supervise_autolive.sh "$TARGET" > /dev/null 2>&1 &
    sleep 30   # 周回立ち上がり待ち（直後の attempt 増をトリガ誤検知しないよう同期し直す）
    base_att=$(grep -c "launch attempt" "$SUPLOG" 2>/dev/null || echo 0)
    base_warn=$(grep -c "閉じられず停滞" "$LOG" 2>/dev/null || echo 0)
    base_clear=$(grep -c "ライブ クリア" "$LOG" 2>/dev/null || echo 0)
  else
    slog "recovery FAILED; giving up"; touch /tmp/i7_freeze_unrecovered; exit 1
  fi
done
