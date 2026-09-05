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
# 5) Mac ロック（終了コード2）→ 待つだけでは直らないので、そう伝えること。
#    以前はこの状態でも「iPhone をロックすると自動再接続」と誤った復旧方法を出し、
#    直らない状態を延々と待ち続けていた（2026-08-06 実際に発生）。
run_case "Macロック中は解除が要ると伝える" 2 "" "Mac がロックされています"
# 6) その裏返し: ロック中に「iPhone をロック」と案内しないこと（誤誘導の回帰）
echo "2" > "$TMP/connected"
rm -f "$I7_SAFE_FLAG" "$I7_BARREN_FLAG"
( cd "$TMP" && TMPDIR_STUB="$TMP" zsh tools/ops/run_until.sh $(( $(date +%s) + 3 )) \
    > "$TMP/lock.log" 2>&1 ) & lockpid=$!
sleep 2; kill -9 $lockpid 2>/dev/null; wait $lockpid 2>/dev/null
if grep -q "iPhone をロックすると自動再接続" "$TMP/lock.log"; then
  ng "Macロック中に iPhone ロックを案内しない"
else
  ok "Macロック中に iPhone ロックを案内しない"
fi

# --- 対話モード（引数なしで実行したとき） -------------------------------------
# pgrep をスタブに差し替える。多重起動ガードは pgrep の出力を見て判断するので、
# **実機で周回が動いているかどうかでテスト結果が変わらないようにする**。
mkdir -p "$TMP/bin"
cat > "$TMP/bin/pgrep" <<'EOS'
#!/bin/zsh
cat "$TMPDIR_STUB/pgrep_out" 2>/dev/null
exit 0
EOS
chmod +x "$TMP/bin/pgrep"
: > "$TMP/pgrep_out"

irun() {  # irun <stdin文字列> <出力ファイル>  → 対話モードを走らせて終了コードを返す
  printf "$1" | ( cd "$TMP" && TMPDIR_STUB="$TMP" PATH="$TMP/bin:$PATH" \
      zsh tools/ops/run_until.sh > "$2" 2>&1 )
}

echo "run_until.sh (対話モード):"

# 7) 引数なし・入力なし → usage を出して非ゼロ終了。
#    `nohup run_until.sh &`（引数なし）を黙ってハングさせないための歯止め。
out="$TMP/i_nostdin.log"
( cd "$TMP" && TMPDIR_STUB="$TMP" PATH="$TMP/bin:$PATH" \
    zsh tools/ops/run_until.sh < /dev/null > "$out" 2>&1 )
rc=$?
if (( rc != 0 )) && grep -q "usage" "$out"; then
  ok "引数なしで入力が無ければ usage を出して落ちる"
else
  ng "引数なしで入力が無ければ usage を出して落ちる（rc=$rc）"; sed 's/^/       /' "$out"
fi

# 8) 無期限＋「曲は触らない」を選び、確認で n → サマリは正しく、起動はしない
out="$TMP/i_keep.log"
irun '4\n1\nn\n' "$out"
if grep -q "2592000秒" "$out" && grep -q -- "--keep-selection" "$out" \
   && grep -q "中止" "$out" && ! grep -q "runner start" "$out"; then
  ok "選択内容をサマリに出し、確認で n なら起動しない"
else
  ng "選択内容をサマリに出し、確認で n なら起動しない"; sed 's/^/       /' "$out"
fi

# 9) 「曲を自動選択」を選んだら --keep-selection を付けないこと。
#    ここを取り違えると、人が選んだ曲を勝手に選び直して LIFE を溶かす。
out="$TMP/i_auto.log"
irun '1\n2\nn\n' "$out"
if grep -q "3600秒" "$out" && ! grep -q -- "--keep-selection" "$out"; then
  ok "曲を自動選択にしたら --keep-selection を付けない"
else
  ng "曲を自動選択にしたら --keep-selection を付けない"; sed 's/^/       /' "$out"
fi

# 10) 多重起動を検出したら拒否する。2プロセスが同じ画面を叩き合うと制御を失う
#     （docs/operations.md 起動前チェック A-1 の機械化）。
echo "99999" > "$TMP/pgrep_out"
out="$TMP/i_dup.log"
irun '4\n1\ny\n' "$out"
rc=$?
if (( rc != 0 )) && grep -q "既に周回" "$out" && ! grep -q "runner start" "$out"; then
  ok "多重起動を検出したら起動を拒否する"
else
  ng "多重起動を検出したら起動を拒否する（rc=$rc）"; sed 's/^/       /' "$out"
fi
: > "$TMP/pgrep_out"

# --- supervise_autolive.sh: 打鍵オプションの受け渡し -------------------------
# **対話モードの「曲は触らない」はこの受け渡しが生きていて初めて効く。**
# I7_TAP_EXTRA が黙って落ちると、run_until.sh は --keep-selection を渡したつもりでも
# autolive には届かず、**人が選んだ曲を勝手に選び直して LIFE を溶かす**
# （ユーザーの恒久要件違反）。しかもログ上は正常に見えるので気づけない。
mkdir -p "$TMP/sup/tools/ops" "$TMP/sup/.venv/bin"
cp "$ROOT/tools/ops/supervise_autolive.sh" "$TMP/sup/tools/ops/"
# 本物の activate と同じく .venv/bin を PATH の先頭へ置く（これが無いとスタブが呼ばれない）
echo 'export PATH="$PWD/.venv/bin:$PATH"' > "$TMP/sup/.venv/bin/activate"
# autolive の代わりに argv を記録して即終了するスタブ
cat > "$TMP/sup/.venv/bin/python" <<'EOS'
#!/bin/zsh
echo "$@" >> "$TMPDIR_STUB/argv"
exit 42          # rc=42 = 安全停止扱い。supervisor は再起動せず抜ける
EOS
chmod +x "$TMP/sup/.venv/bin/python"

sup_case() {  # sup_case <name> <I7_TAP_EXTRA> <期待する文字列> <期待するか(1/0)>
  : > "$TMP/argv"
  ( cd "$TMP/sup" && TMPDIR_STUB="$TMP" \
      I7_AUTORUN_LOG="$TMP/sup_autorun.log" I7_SUPERVISOR_LOG="$TMP/sup_sup.log" \
      I7_SAFE_FLAG="$TMP/sup_safe" I7_TAP_EXTRA="$2" \
      zsh tools/ops/supervise_autolive.sh $(( $(date +%s) + 5 )) > /dev/null 2>&1 )
  local got=0
  grep -q -- "$3" "$TMP/argv" && got=1
  if (( got == $4 )); then ok "$1"; else
    ng "$1"; sed 's/^/       /' "$TMP/argv"
  fi
}

echo "supervise_autolive.sh:"
# 11) I7_TAP_EXTRA が autolive の引数に載ること
sup_case "I7_TAP_EXTRA を autolive へ渡す" "--keep-selection" "--keep-selection" 1
# 12) 既定の打鍵オプションを消さずに**追記**すること（既定はこのスクリプトが真実の情報源）
sup_case "既定の --green-hold を消さない" "--keep-selection" "--green-hold" 1
# 13) 空なら余計なものは付かない
sup_case "I7_TAP_EXTRA が空なら何も足さない" "" "--keep-selection" 0
# 14) 本番のログに書いていないこと（テストが周回のログを汚さないための歯止め）
if [[ -s "$TMP/sup_sup.log" ]]; then
  ok "supervisor のログを差し替えられる"
else
  ng "supervisor のログを差し替えられる（本番 /tmp/i7_supervisor.log に書いた疑い）"
fi

# 本番の資源に触れていないことを確認する（テストが周回を壊さないための歯止め）。
# **既に存在していたものは対象外**。本番の安全停止が残したフラグを「テストが作った」と
# 誤検知していた（実際に 2026-08-02 04:56 の停止フラグで誤検出した）。
for f in /tmp/i7_safe_stop_fired /tmp/i7_barren_fired; do
  if [[ -e $f && -z ${PRE_EXISTING[(r)$f]} ]]; then
    ng "本番のフラグ $f を作ってしまった"
  fi
done
exit $fail
