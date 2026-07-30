#!/bin/zsh
# PAUSE嵐ガード: autolive ログを監視し、直近60秒の「PAUSE → 再開」が GUARD_MAX 回を
# 超えたら周回（supervisor + autolive）を強制停止する。再接続病(§17.10)が夜間に再発した
# 場合に LIFE/きなこパンの浪費を防ぐ。停止したら /tmp/i7_pause_guard_fired を残す。
set -u
LOG="/tmp/i7_autorun.log"
GLOG="/tmp/i7_pause_guard.log"
GUARD_MAX=5
log() { echo "[$(date '+%H:%M:%S')] $*" >> "$GLOG"; }
log "guard start (max ${GUARD_MAX}/60s)"
while :; do
  sleep 30
  [[ -f "$LOG" ]] || continue
  # ログ行頭の経過秒 [ 123.4s] を使い、最終行から60秒以内の PAUSE→再開 行を数える
  n=$(python3 - "$LOG" <<'EOF'
import re, sys
lines = open(sys.argv[1], errors="ignore").readlines()[-400:]
# 複数 run が混在すると経過秒が巻き戻るため、最後の「自動周回を開始」以降だけを見る
for i in range(len(lines) - 1, -1, -1):
    if "自動周回を開始" in lines[i]:
        lines = lines[i:]
        break
ts = [float(m.group(1)) for l in lines if (m := re.match(r"\[\s*([0-9.]+)s\]", l)) and "PAUSE → 再開" in l]
allts = [float(m.group(1)) for l in lines if (m := re.match(r"\[\s*([0-9.]+)s\]", l))]
print(sum(1 for t in ts if allts and allts[-1] - t <= 60))
EOF
)
  if (( n > GUARD_MAX )); then
    log "PAUSE storm detected (n=$n/60s) -> killing farm"
    pkill -f supervise_autolive.sh
    pkill -f "autolive.py"
    touch /tmp/i7_pause_guard_fired
    log "farm killed; guard exiting"
    exit 1
  fi
done
