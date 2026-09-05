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
SELF="${0:A}"          # 対話モードで自分自身を再起動するため、cd の前に絶対パス化する
cd "$(dirname "$SELF")/../.."

# --- 引数なしで実行されたときの対話セットアップ -------------------------------
# **引数ありの動作は従来どおり。** テストと docs は `run_until.sh <target_epoch>` を
# 直接呼ぶので、その経路には一切手を入れない。対話は「選ばせて → 確認して →
# 自分自身をバックグラウンドで起動する」だけで、周回のロジックには関与しない。
#
# TTY 判定（`[[ -t 0 ]]`）はしない。それだとテストからプロンプトを駆動できず、
# 本体にテスト専用の抜け穴を作ることになる。代わりに**普通に read して EOF なら
# usage で落とす**。`nohup run_until.sh &`（引数なし）は stdin が /dev/null なので
# 即 EOF になり、黙ってハングせず明確に落ちる。
usage_and_exit() {
  cat >&2 <<'USAGE'

usage: run_until.sh <target_epoch>
       run_until.sh                 引数なしで実行すると対話で設定を選べます

対話モードは端末からの入力が必要です。`nohup run_until.sh &` のように入力の
無い状態で引数なし起動はできません（その場合は終了時刻を引数で渡してください）。
USAGE
  exit 2
}

ask() {   # ask <プロンプト> → 1行読んで REPLY_LINE に入れる。EOF なら usage で終了
  printf '%s' "$1" >&2
  IFS= read -r REPLY_LINE || usage_and_exit
}

interactive_setup() {
  # **多重起動ガード。** 2プロセスが同じ画面を叩き合うと制御を失う。
  # docs/operations.md の起動前チェック A-1 を機械化したもの（ops スクリプトには
  # 従来これが無く、人間の目視に頼っていた）。
  local dup others
  dup=$(pgrep -f 'tools/ops/supervise_autolive\.sh|tools/autolive\.py' 2>/dev/null)
  others=$(pgrep -f 'tools/ops/run_until\.sh' 2>/dev/null | grep -v "^$$\$")
  if [[ -n "${dup}${others}" ]]; then
    echo "既に周回プロセスが動いています (pid: ${dup//$'\n'/ } ${others//$'\n'/ })" >&2
    echo "先に止めてください:" >&2
    echo "  pkill -f run_until; pkill -f supervise_autolive; pkill -f tools/autolive" >&2
    exit 2
  fi

  cat >&2 <<'CHECK'
起動前の確認（毎回）:
  [ ] イベント楽曲の導線から入っている（ホームの LIVE から入ると通常ライブで pt が付かない）
  [ ] 難易度 EASY（ライフ -15）
  [ ] ブースト 3倍
  [ ] オート OFF（ON のままだとブリンクドリンクを1ライブ3個消費する）
  [ ] 編成画面（START が見える）まで進めてある

CHECK

  local secs="" label="" t now
  while [[ -z "$secs" ]]; do
    cat >&2 <<'MENU'
実行時間:
  1) 1時間   2) 2時間   3) 4時間   4) 無期限(30日)   5) 終了時刻を指定 (HH:MM)
MENU
    ask "> "
    case "$REPLY_LINE" in
      1) secs=3600;    label="1時間" ;;
      2) secs=7200;    label="2時間" ;;
      3) secs=14400;   label="4時間" ;;
      4) secs=2592000; label="無期限(30日)" ;;
      5) ask "終了時刻 (HH:MM) > "
         t=$(date -j -f '%Y-%m-%d %H:%M:%S' "$(date +%F) ${REPLY_LINE}:00" +%s 2>/dev/null)
         if [[ -z "$t" ]]; then
           echo "時刻の形式が不正です（例: 23:45）" >&2; continue
         fi
         now=$(date +%s)
         (( t <= now )) && t=$(( t + 86400 ))   # 過ぎていれば翌日とみなす
         secs=$(( t - now )); label="${REPLY_LINE} まで" ;;
      *) echo "1〜5 で答えてください" >&2 ;;
    esac
  done

  local extra="" song=""
  while [[ -z "$song" ]]; do
    cat >&2 <<'MENU'
楽曲選択画面での振る舞い:
  1) 人が選んだまま触らない（推奨）
  2) Don't Analyze Me + EASY を自動選択（累計イベント用の既定動作）
MENU
    ask "> "
    case "$REPLY_LINE" in
      1) extra="--keep-selection"; song="人が選んだまま触らない" ;;
      2) extra="";                 song="Don't Analyze Me + EASY を自動選択" ;;
      *) echo "1 か 2 で答えてください" >&2 ;;
    esac
  done

  local target=$(( $(date +%s) + secs ))
  cat >&2 <<SUMMARY

  期間     : ${label} (${secs}秒) → $(date -r "$target" '+%Y-%m-%d %H:%M:%S') まで
  楽曲     : ${song}
  追加opts : ${extra:-（なし。supervisor の既定のみ）}
SUMMARY
  ask "開始しますか? [y/N] > "
  case "$REPLY_LINE" in
    y|Y|yes|YES) ;;
    *) echo "中止しました" >&2; exit 0 ;;
  esac

  # 打鍵オプションの既定値は supervise_autolive.sh が持っている。ここで
  # I7_TAP_OPTS を組み立てると既定が2箇所に散って片方だけ古くなるので、
  # **追記用の I7_TAP_EXTRA だけを渡す**（既定の真実の情報源は1つのまま）。
  export I7_TAP_EXTRA="$extra"
  nohup "$SELF" "$target" > /dev/null 2>&1 &
  echo "バックグラウンドで起動しました (pid $!)" >&2
  echo "  進行を見る : tail -f /tmp/i7_autorun.log" >&2
  echo "  止める     : pkill -f run_until; pkill -f supervise_autolive;" >&2
  echo "               pkill -f tools/autolive; pkill -f 'caffeinate -dimsu'" >&2
  exit 0
}

(( $# == 0 )) && interactive_setup

TARGET="${1:?usage: run_until.sh <target_epoch>}"
# パスは環境変数で差し替え可能にする（テストが本番のログ・フラグを壊さないため）。
LOG="${I7_RUNNER_LOG:-/tmp/i7_runner.log}"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# 接続状態を終了コードで返す。
#   0 = 接続していてゲーム画面が見えている
#   1 = 切断（iPhone をロックすれば自動復帰しうる。待つ価値がある）
#   2 = **Mac がロックされている**（人がロック解除するまで絶対に復帰しない）
#
# 2 を分けているのは実害があったため（2026-08-06）。ウィンドウが縦長かどうかだけで
# 判定していた頃は、Mac ロック中も「ミラーリング切断中（iPhone をロックすると自動再接続）」
# と**誤った復旧方法**をログに出し、直らない状態を延々と待ち続けていた。
# ロック中はキャプチャに壁紙しか写らない（アプリのウィンドウが合成されない）ので、
# 画面の見た目からは切断と区別できない。詳細は docs/device-findings.md。
connected() {
  .venv/bin/python - <<'PY' 2>/dev/null
import sys
sys.path.insert(0, "tools")
try:
    import Quartz
    if (Quartz.CGSessionCopyCurrentDictionary() or {}).get("CGSSessionScreenIsLocked"):
        sys.exit(2)
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

SAFE_FLAG="${I7_SAFE_FLAG:-/tmp/i7_safe_stop_fired}"
BARREN_FLAG="${I7_BARREN_FLAG:-/tmp/i7_barren_fired}"
rm -f "$SAFE_FLAG" "$BARREN_FLAG"

log "runner start (target=$(date -r "$TARGET" '+%Y-%m-%d %H:%M:%S'))"
waiting=0
while :; do
  now=$(date +%s)
  remain=$(( TARGET - now ))
  (( remain <= 0 )) && { log "target reached; done"; break; }

  connected; conn=$?
  if (( conn == 0 )); then
    (( waiting )) && log "接続を確認 → 周回を再開"
    waiting=0
    log "supervisor 起動（残り ${remain}s）"
    tools/ops/supervise_autolive.sh "$TARGET"
    log "supervisor 終了"
    # supervisor が安全停止／空転打ち切りで抜けたとき、**接続はあるのに再起動すると
    # 同じ理由でまた止まる**（runner レベルの無限ループ）。切断なら下の connected() が
    # false になって待機に入るので、ここで見るのは「繋がっているのに止まった」場合だけ。
    if [[ -e "$SAFE_FLAG" || -e "$BARREN_FLAG" ]]; then
      if connected; then   # 0 のときだけ「繋がっているのに止まった」＝人手が必要
        log "人手が必要な停止（$( [[ -e "$SAFE_FLAG" ]] && echo safe_stop || echo barren )）"
        log "同じ理由で止まるため runner を終了する。/tmp/i7dbg/ のスクショを確認すること"
        break
      fi
      # 切断が原因だった → フラグを消して待機ループへ（復帰したら再開する）
      rm -f "$SAFE_FLAG" "$BARREN_FLAG"
    fi
  else
    # 待機理由が変わったときだけログを出す（30秒ごとに同じ行を並べない）
    if (( conn == 2 )); then
      if (( waiting != 2 )); then
        log "**Mac がロックされています。** ロック解除するまで復帰しません"
        log "（iPhone をロックしても直りません。Mac のロックを解除してください）"
        waiting=2
      fi
    else
      if (( waiting != 1 )); then
        log "ミラーリング切断中（iPhone をロックすると自動再接続）。復帰まで待機する"
        waiting=1
      fi
    fi
    sleep 30
  fi
done
log "runner done"
