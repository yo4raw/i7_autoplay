#!/bin/zsh
# genuine入力方式のA/B: 各modeで autolive を一定秒走らせ PAUSE数/クリア数を集計。
set -u
cd "$(dirname "$0")/../.."
source .venv/bin/activate
SECS="${1:-45}"
shift 2>/dev/null || true
MODES=("$@")
if (( ${#MODES} == 0 )); then MODES=(0 delta movepair drag scroll assoc session); fi
OUT=/tmp/i7dbg
mkdir -p "$OUT"
RES="$OUT/ab_results.txt"
: > "$RES"
echo "AB start secs=$SECS modes=${MODES[*]}" | tee -a "$RES"
for m in "${MODES[@]}"; do
  log="$OUT/mode_${m}.log"
  I7_CLICK_MODE="$m" python -u tools/autolive.py --loops 9 --max-seconds "$SECS" --no-esc > "$log" 2>&1
  p=$(grep -c "PAUSE → 再開" "$log")
  c=$(grep -c "クリア" "$log")
  gp=$(grep -c "state=gameplay" "$log")  # verbose無しなら0
  echo "mode=$m pauses=$p clears=$c" | tee -a "$RES"
  sleep 2
done
echo "AB done" | tee -a "$RES"
