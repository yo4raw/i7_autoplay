---
name: run-forever
description: Use when asked to start, restart, or resume the IDOLiSH7 event loop right away with no time limit (「周回を無制限に」「すぐ周回開始」「周回を始めて」「周回を再開」), including after a safe stop.
---

# 無制限周回の即時開始

対話メニューを飛ばし、`run_until.sh` を 30 日ターゲットで裏起動する。確認は pgrep と
スクショ 1 枚で済ませ、**ユーザーに質問して止まらない**。画面はクリックで直さない。

## 手順（順番どおり。1 つでも外れたら起動せず報告）

1. 多重起動 0 件: `pgrep -fl 'run_until\.sh|supervise_autolive\.sh|tools/autolive\.py'`
   （`\.` は自分のシェル行に引っかからないため）。何か出たら**起動せず手順 6 へ**。
   ライブ途中の kill は LIFE を丸ごと捨てる。
2. 接続: `.venv/bin/python tools/driver.py info` の `w > h`（横向き）。縦長なら切断中。
3. 撮って Read: `mkdir -p /tmp/i7dbg; .venv/bin/python tools/driver.py shot /tmp/i7dbg/prelaunch.png`
   - 編成画面で START が見える（楽曲選択画面でも可）
   - 左下パネルが **ブースト 3倍（またはイベント仕様の上限 10倍）/ オート OFF**
     （2026-10 「Encounter Love Song」イベントはブースト上限 10倍・スキップあり。
     ユーザーが 10倍 を選んだ場合はそのまま可）
   - 難易度は**人が選んだまま**（ユーザー指定 2026-10-20。EASY でなくても止めない）。
     LIFE コストは難易度とブーストで変わる（EASY・3倍で -15、10倍イベントで -100）
   - **右上のステラ所持数を控える**（ダイアログを開かなくても見える。終了後に同じ数か確認する）
4. 起動（曲は人が選んだまま。既定の打鍵オプションは supervisor が持つので `I7_TAP_EXTRA` で追記する）:
   ```bash
   I7_TAP_EXTRA="--keep-selection" nohup tools/ops/run_until.sh $(( $(date +%s) + 2592000 )) > /dev/null 2>&1 &
   ```
5. 5 秒後 `cat /tmp/i7_runner.log` に `supervisor 起動`、60 秒後 `tail /tmp/i7_autorun.log` に
   `[auto-circles]` と `編成画面 → START` が出ることを確認し、ステラ数とともに報告する。
6. 以後は `assets/prompts/supervisor_loop.md` を読み、/loop（自己ペース）で監視する。正常なら何もしない。

## 知っておくこと

- 「無制限」= 30 日（対話メニューの「無期限(30日)」と同じ値）。休憩時間に入ると `break_time` で安全停止し、
  接続があるので runner も終了する。再開は人が休憩明けを確認してからこの skill を再実行。
- きなこパンが尽きると `kinako_missing` で安全停止する。ステラは使わない。
- 引数付き起動には多重起動ガードが無い。手順 1 は省けない。
- 止めるのはリザルト画面が出てから:
  `pkill -f run_until; pkill -f supervise_autolive; pkill -f tools/autolive; pkill -f 'caffeinate -dimsu'`
