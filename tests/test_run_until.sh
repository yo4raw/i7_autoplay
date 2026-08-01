#!/bin/zsh
# run_until.sh の分岐を実際に走らせて検証する（実機不要）。
#
# supervise_autolive.sh と connected() を差し替えたスタブ環境で動かし、
# 「人手が必要な停止では runner を終了する」「切断中は待機する」を確かめる。
# シェルの分岐はユニットテストで型検査できないので、実行して確かめるしかない。
set -u
cd "$(dirname "$0")/.."
ROOT=$PWD
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fail=0
ok()   { echo "  ok   - $1" }
ng()   { echo "  NG   - $1"; fail=1 }

# --- スタブ環境を作る ---------------------------------------------------------
mkdir -p "$TMP/tools/ops" "$TMP/.venv/bin"
cp "$ROOT/tools/ops/run_until.sh" "$TMP/tools/ops/"
# connected() は .venv/bin/python を呼ぶ。終了コードを $TMP/connected で制御する。
cat > "$TMP/.venv/bin/python" <<'EOS'
#!/bin/zsh
cat > /dev/null            # ヒアドキュメントを読み捨てる
exit $(cat "$TMPDIR_STUB/connected" 2>/dev/null || echo 0)
EOS
chmod +x "$TMP/.venv/bin/python"

# 本番と資源を共有しないよう、ログとフラグは全てテンポラリへ隔離する
# 実行開始時点で既にあった本番フラグを記録しておく（テストが作ったものと区別するため）
PRE_EXISTING=()
for f in /tmp/i7_safe_stop_fired /tmp/i7_barren_fired; do
  [[ -e $f ]] && PRE_EXISTING+=($f)
done

export I7_RUNNER_LOG="$TMP/runner.log"
export I7_SAFE_FLAG="$TMP/safe_fired"
export I7_BARREN_FLAG="$TMP/barren_fired"

run_case() {
  local name=$1 connected=$2 flag=$3 expect=$4
  echo "$connected" > "$TMP/connected"
  rm -f "$I7_SAFE_FLAG" "$I7_BARREN_FLAG"
  # supervisor スタブ: 指定のフラグを立てて即座に戻る
  cat > "$TMP/tools/ops/supervise_autolive.sh" <<EOS
#!/bin/zsh
[[ -n "$flag" ]] && touch "$flag"
sleep 0.2
EOS
  chmod +x "$TMP/tools/ops/supervise_autolive.sh"
  local out="$TMP/out.log"
  # macOS には timeout が無いのでバックグラウンド実行＋見張りで打ち切る
  ( cd "$TMP" && TMPDIR_STUB="$TMP" zsh tools/ops/run_until.sh \
      $(( $(date +%s) + 8 )) > "$out" 2>&1 ) &
  local pid=$!
  local waited=0
  while kill -0 $pid 2>/dev/null && (( waited < 120 )); do
    sleep 0.1; waited=$(( waited + 1 ))
  done
  kill -9 $pid 2>/dev/null
  wait $pid 2>/dev/null
  if grep -q "$expect" "$out"; then ok "$name"; else
    ng "$name（期待: $expect）"; sed 's/^/       /' "$out"
  fi
}

echo "run_until.sh:"
# 1) 接続あり＋安全停止フラグ → 人手が必要なので runner を終了する
run_case "安全停止したら runner を終了する" 0 "$I7_SAFE_FLAG" "人手が必要な停止"
# 2) 接続あり＋空転フラグ → 同上
run_case "空転打ち切りでも runner を終了する" 0 "$I7_BARREN_FLAG" "人手が必要な停止"
# 3) 接続なし → 待機する（supervisor を起動しない）
run_case "切断中は待機する" 1 "" "ミラーリング切断中"
# 4) 接続あり＋フラグ無し → 目標時刻まで回り続けて正常終了
run_case "正常時は目標時刻まで回る" 0 "" "target reached"

# 本番の資源に触れていないことを確認する（テストが周回を壊さないための歯止め）。
# **既に存在していたものは対象外**。本番の安全停止が残したフラグを「テストが作った」と
# 誤検知していた（実際に 2026-08-02 04:56 の停止フラグで誤検出した）。
for f in /tmp/i7_safe_stop_fired /tmp/i7_barren_fired; do
  if [[ -e $f && -z ${PRE_EXISTING[(r)$f]} ]]; then
    ng "本番のフラグ $f を作ってしまった"
  fi
done
exit $fail
