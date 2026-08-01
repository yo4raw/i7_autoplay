# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
（このファイルは、本リポジトリで作業する将来の Claude Code への手引きです。以下は日本語で記述します。）

## 概要

macOS の **iPhone ミラーリング** 越しに **アイドリッシュセブン (IDOLiSH7)** の「累計イベント」
ライブを自動周回するツール。ミラーリングウィンドウをキャプチャ → 現在画面を認識 → 合成タップを
送り、イベントライブを繰り返しクリアする。ビルドシステムは無く、スクリプト＋テンプレ画像＋
ドキュメントから成る。

**真実の情報源は [`docs/README.md`](docs/README.md)。** FSM の全体像、実機で確認した画面遷移、
正確な座標、苦労して判明したプラットフォーム制約はそこから辿れる。挙動を変える前に必ず
[`docs/device-findings.md`](docs/device-findings.md) を読むこと。

コードの入口は [`tools/README.md`](tools/README.md)。

## 絶対規則（破ると課金事故・周回が無意味になる）

1. **LIFE 回復はきなこパンのみ。ステラは絶対に使わない。** ステラのボタン座標は意図的に
   コードに持たせていない。きなこパンが尽きたら**フォールバックせず停止**する。
   > **⚠️ この規則は現在のコードでは守られていない（2026-07-31 判明・既遂）。**
   > きなこパンが 0 個になるとダイアログから**きなこパン行が消えて上に詰まり**、
   > `ANCH_KINAKO` の着弾点がステラの「回復」ボタン中央になる。実機で
   > ステラ所持が 58→55→52 と3個ずつ減っていた。ログには「ステラ不使用」と出るため
   > 気づけない。**周回前にきなこパン残量とステラ所持数を必ず確認すること。**
   > 詳細と対策: [`docs/improvements.md`](docs/improvements.md) C-1
2. **難易度は必ず EASY。**
3. **イベント楽曲へはホーム左下のイベントリボンから入る。** ホームの「LIVE」ボタンから入ると
   通常ライブで、クリアしてもイベント pt が一切付かない。
4. **ブースト倍率は必ず 3 倍。**
5. **オートライブは使わない（大前提・毎回確認）。** オートは1ライブにつきブリンドリンク
   3個を消費するため。周回開始時は毎回、楽曲選択下部パネルが
   「ブースト 3倍／**オート OFF**」であることを確認してから START する
   （ユーザーは今後これを指示しない。言われなくても必ず確認する）。
   周回は tap エンジンで行い、EASY で SS グレードを目指す。
6. **未知の明るい画面ではクリックせず停止する。** 盲目連打はしない（課金ボタンの誤タップ防止）。
7. **合成入力は `kCGHIDEventTap` かつ HIDSystemState ソース＋実カーソルのワープ。**
   これ以外の経路ではゲームが数秒ごとに PAUSE する。実行中は Mac のマウスを操作しないこと。
8. **キャプチャは `mss` を使う。** `screencapture -l<windowid>` はフォーカスを奪い PAUSE させる。
9. **座標系は2つある。** `click_window(xf,yf)` はウィンドウ相対、`click_content(xf,yf)` は
   内容矩形相対。混同すると誤クリックする。

## 精度が出ないときの定石（2026-07-31 の教訓）

**パラメータを触る前に、必ずこの2つを測る。**

1. **打鍵回数**（ライブ終了時に `打鍵N回 / 判定Mフレーム` としてログに出る）
   - ノーツ数より少ない → **検出**の問題（円座標のズレ・しきい値）
   - ノーツ数と同等以上なのに MISS が多い → **タイミング**の問題
2. **ループ周波数**（判定フレーム数 ÷ ライブ長）
   - **30 FPS 前後が正常。** これを大きく下回るなら、まずそこを直す

実際にあった事故: 打鍵ループが **3.3 FPS** しか出ておらず（PAUSE 照合が 0.25 秒おきに
147〜246ms 消費していた）、ノーツ到達を最大 300ms 遅れて検出していた。この状態で
`--note-lead` を 0.025→0.04→0.055 と「調整」していたが、それは**検出遅れを早撃ちで
埋めていただけ**で、根本原因を見ていなかった。ループを 37 FPS に直したら
MISS 120→5・SCORE 66k→34万になり、正しい lead は 0.02 だと判明した。

つまり **lead が大きい値でしか合わないときは、ループが遅い可能性を疑うこと。**

**ただし速ければ良いわけではない。** 38 FPS からさらに 48 FPS へ上げたら
PERFECT 54.5→37.5（3.5σ）と有意に悪化し、撤回して復帰した
（[`docs/device-findings.md`](docs/device-findings.md)「打鍵ループは速ければ良いわけではない」）。
`_gameplay_timing` 末尾の `time.sleep(0.005)` を無駄と判断して外さないこと。

**効果測定は必ず分布で。** 同一設定でも PERFECT は ±12 ばらつく。
`tools/ops/result_log.py` で各条件10件以上を貯めて σ で判断する。単発比較は誤差に埋もれる。

## コマンド

```bash
# セットアップ（Python 3.11+。リポジトリは Python 3.14 の .venv を使用）
python3 -m venv .venv && source .venv/bin/activate
pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa opencv-python mss numpy Pillow

# 無人周回の標準手順（推奨。落ちても supervisor が自動再起動する）
nohup tools/ops/supervise_autolive.sh $(( $(date +%s) + 7200 )) > /dev/null 2>&1 &

# 単発（ゲームをイベントライブ開始済み or 楽曲選択画面にしてから実行）
python tools/autolive.py --loops 50 --max-seconds 7200 --flick --auto-circles
python tools/autolive.py --loops 3 --verbose          # 短いデバッグ実行
python tools/autolive.py --loops 2 --dry-run          # 判定のみ・クリックしない

# リザルト成績の蓄積（周回と並走。チューニング効果は1ライブでは誤差に埋もれる）
python -u tools/ops/result_log.py 7200 <tag>
python tools/ops/result_log.py montage <tag>          # 蓄積ぶんを1枚にまとめる

# 手動ドライバ（探索／テンプレ取得用。座標はウィンドウ相対 0..1）
python tools/driver.py info
python tools/driver.py shot out.png
python tools/driver.py click <xfrac> <yfrac>

# テスト（実機不要・合成フレームとコーパス）
.venv/bin/python -m unittest discover -s tests
```

**`--auto-circles` は必須級。** 円座標は機種差で数十 px ずれ、無効だと MISS が跳ね上がる
（実測 MISS 51・グレード B）。補正値は `.autocal_circles.json` にキャッシュされ、
再起動時に即復元される。supervisor は既定で付ける。

**ライブ（曲）の途中で autolive を止めないこと。** その周回ぶんの LIFE が丸ごと無駄になる。
改善が必要でもリザルト画面が出るまで待つ（`detect()` が `gameplay`/`pause` を返す間は待機）。

事前に一度、**スクリプトを起動するホストプロセス**（Terminal / iTerm / VS Code など。.py ファイル
ではない）へ、システム設定で **画面収録** と **アクセシビリティ** を付与し、そのホストを
再起動すること。macOS のアップデートでこれらは無言で無効化される。
詳細は [`docs/setup.md`](docs/setup.md)。

リンタ／フォーマッタは未設定。デバッグ用スクショは `/tmp/i7dbg/` に保存される。

## LLM copilot（廉価モデル併用の無人運用）

**役割分担の原則（ユーザー指定・2026-07-31）**: LLM の担当はあくまで**監視と改善**
（周回状況の見張り・異常の判断・スクリプトやパラメータの改善）。**実際のゲーム操作
（タップ・ナビゲーション・周回）はスクリプト**（`tools/autolive.py` / `tools/driver.py` /
`tools/ops/`）**が行う**。LLM が画面を1クリックずつアドホックに操作するのは開発・検証時の
例外に留め、恒常的に必要になった操作手順はスクリプトへ実装して自動化する
（イベント導線ナビも暫定運用であり、スクリプト化が改善対象）。周回の安全性・成立が
LLM に依存しない設計を維持すること。

プロンプト資産は `assets/prompts/`（**Fable 5 作成済み。実装・運用時に書き直さずそのまま使う**）。
設計は [`docs/superpowers/specs/2026-07-10-llm-copilot-design.md`](docs/superpowers/specs/2026-07-10-llm-copilot-design.md)。

- **監視・復旧スーパーバイザー**: このリポジトリで Claude Code セッションを開き（Haiku/Sonnet で足りる）
  `assets/prompts/supervisor_loop.md を読み、その指示に従って /loop で監視して` と指示する
  （自己ペース /loop、目安 20 分間隔）。正常周回中は何もしないのが規律。
  `nohup tools/ops/supervise_autolive.sh <target_epoch> &` と併用可。
- **イベント導線ナビ**: ホーム画面にあるとき
  `assets/prompts/event_navigation.md を読み、ホームからイベントライブ開始まで進めて` と指示する。
  ライブが始まったら `python tools/autolive.py --loops N --flick` を起動。
- 認証: `ANTHROPIC_API_KEY` または `ant auth login`。API/LLM が落ちても従来の安全停止に
  劣化するだけで、周回の安全性は LLM に依存しない設計を維持すること。
