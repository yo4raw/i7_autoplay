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
2. **難易度は必ず EASY。**
3. **イベント楽曲へはホーム左下のイベントリボンから入る。** ホームの「LIVE」ボタンから入ると
   通常ライブで、クリアしてもイベント pt が一切付かない。
4. **ブースト倍率は必ず 3 倍。**
5. **未知の明るい画面ではクリックせず停止する。** 盲目連打はしない（課金ボタンの誤タップ防止）。
6. **合成入力は `kCGHIDEventTap` かつ HIDSystemState ソース＋実カーソルのワープ。**
   これ以外の経路ではゲームが数秒ごとに PAUSE する。実行中は Mac のマウスを操作しないこと。
7. **キャプチャは `mss` を使う。** `screencapture -l<windowid>` はフォーカスを奪い PAUSE させる。
8. **座標系は2つある。** `click_window(xf,yf)` はウィンドウ相対、`click_content(xf,yf)` は
   内容矩形相対。混同すると誤クリックする。

## コマンド

```bash
# セットアップ（Python 3.11+。リポジトリは Python 3.14 の .venv を使用）
python3 -m venv .venv && source .venv/bin/activate
pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa opencv-python mss numpy Pillow

# 自動周回（ゲームをイベントライブ開始済み or 楽曲選択画面にしてから実行）
python tools/autolive.py --loops 50 --max-seconds 7200 --flick
python tools/autolive.py --loops 3 --verbose          # 短いデバッグ実行
python tools/autolive.py --loops 2 --dry-run          # 判定のみ・クリックしない

# 手動ドライバ（探索／テンプレ取得用。座標はウィンドウ相対 0..1）
python tools/driver.py info
python tools/driver.py shot out.png
python tools/driver.py click <xfrac> <yfrac>

# テスト（実機不要・合成フレームとコーパス）
.venv/bin/python -m unittest discover -s tests
```

事前に一度、**スクリプトを起動するホストプロセス**（Terminal / iTerm / VS Code など。.py ファイル
ではない）へ、システム設定で **画面収録** と **アクセシビリティ** を付与し、そのホストを
再起動すること。macOS のアップデートでこれらは無言で無効化される。
詳細は [`docs/setup.md`](docs/setup.md)。

リンタ／フォーマッタは未設定。デバッグ用スクショは `/tmp/i7dbg/` に保存される。

## LLM copilot（廉価モデル併用の無人運用）

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
