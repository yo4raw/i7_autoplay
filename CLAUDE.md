# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
（このファイルは、本リポジトリで作業する将来の Claude Code への手引きです。以下は日本語で記述します。）

## 概要

macOS の **iPhone ミラーリング** 越しに **アイドリッシュセブン (IDOLiSH7)** の「累計イベント」
ライブを自動周回するツール。ミラーリングウィンドウをキャプチャ → 現在画面を認識 → 合成タップを
送り、イベントライブを繰り返しクリアする。ビルドシステムもテストも無く、スクリプト2本＋テンプレ
画像＋仕様書から成る。

**`docs/specification.md` が真実の情報源**。FSM の全体像、実機で確認した画面遷移、正確な座標、苦労して
判明したプラットフォーム制約はすべてここにある。挙動を変える前に必ず読むこと。

## コマンド

```bash
# セットアップ（Python 3.11+。リポジトリは Python 3.14 の .venv を使用）
python3 -m venv .venv && source .venv/bin/activate
pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa opencv-python mss numpy Pillow

# 自動周回（ゲームをイベントライブ開始済み or 楽曲選択画面にしてから実行）
python tools/autolive.py --loops 50 --max-seconds 7200
python tools/autolive.py --loops 3 --verbose          # 短いデバッグ実行（毎フレーム状態をログ）
python tools/autolive.py --loops 2 --dry-run          # 判定のみ・クリックしない

# 手動ドライバ（探索／テンプレ取得用。座標はウィンドウ相対 0..1）
python tools/driver.py info                            # ウィンドウ範囲＋スケール
python tools/driver.py shot out.png                    # mss でスクショ（フォーカスを奪わない）
python tools/driver.py click <xfrac> <yfrac>
python tools/driver.py clickshot <xfrac> <yfrac> out.png [wait]
python tools/driver.py swipe <x1> <y1> <x2> <y2>
```

事前に一度、**スクリプトを起動するホストプロセス**（Terminal / iTerm / VS Code など。.py ファイル
ではない）へ、システム設定で **画面収録（Screen Recording）** と **アクセシビリティ（Accessibility）**
を付与し、そのホストを再起動すること。macOS のアップデートでこれらは無言で無効化される。

リンタ／フォーマッタ／テストは未設定。デバッグ用スクショは `/tmp/i7dbg/` に保存される。

## アーキテクチャ

`tools/` 配下の2層構成:

- **`driver.py`** — 低レベル I/O。ミラーリングウィンドウ検出（`CGWindowListCopyWindowInfo`、owner が
  `iPhone Mirroring`/`iPhoneミラーリング`）、**`mss`** でキャプチャ、`CGEventPost` でクリック／スワイプ、
  アプリ強制前面化（`NSRunningApplication.activateWithOptions_`）。手動ナビゲーションやテンプレ取得に
  単体で使う。
- **`autolive.py`** — 周回 FSM。メインループは **capture → detect → act**: フレーム取得 → 内容矩形検出
  → 状態分類 → 1アクション実行、を繰り返す。状態分類は **明るさゲート＋テンプレマッチング**
  （`assets/templates/*.png`、マルチスケール `TM_CCOEFF_NORMED`）。判定順は固定で重要:
  `pause → gameplay(暗) → lifeshort → friendreq → replay → rankup → dldialog → story → closex →
  result → songselect → friendselect → formation → menu`（story=「ストーリー遷移しますか？」→いいえ）。
  friendselect は固定ラベル「アピールスキル」テンプレで判定（フレンドのスキル文は可変なため）。
  ループは「ライブ ⇄ リザルト」をゲーム内「連続ライブ再プレイ→はい」で回し、連戦終了で楽曲選択へ
  戻った場合は songselect→friendselect→formation を自動ナビして再開する（ホームからは辿らない）。
- **ライブ中の打鍵 `--tap-mode`（既定 timing）**: timing=各円ROIの白割合がベースラインから跳ね上がる
  瞬間にノーツ到達を検出してタップ（`_gameplay_timing`/`_note_present`、`NOTE_*`定数）。ノーツ無し区間は
  `_keepalive` が genuine 入力を出し続け PAUSE を防ぐ（これが無いと止まると再 PAUSE）。`--calibrate`/
  `--note-*` で調整。rotate=5円50Hz巡回連打（フォールバック）。種別はタップ最適化で、フリック/スライド/
  ロングは頭だけ＝部分点（スワイプは PAUSE 防止が効かないため非対応）。赤ノーツは `--flick` で
  到達直前検色→外向きフリック（実機検証済み・MISS 14→3）。
- **ハイブリッド種別先読み（実験的・既定OFF, §17.11）**: `--predict` で `note_engine` の
  track（スポーン検出→追跡→色/レーン/ETA）を並走させ、roi 発火時に緑=次の緑のETAまで
  ホールド／赤=フリックを出し分け。不調時は通常タップに劣化（フェイルソフト）。
  `--auto-circles` はライブ突入時に円リングを画像検出して `CIRCLES` を自動補正
  （4円全一致時のみ・失敗時は現行値維持＝機種非依存化）。テストは
  `.venv/bin/python -m unittest discover -s tests`（実機不要・合成フレーム）。

### 非自明な制約（コードがこういう形になっている理由）

- **iPhone ミラーリングに届くのは `kCGHIDEventTap` だけ。** `kCGSessionEventTap` /
  `kCGAnnotatedSessionEventTap` へ送ったクリックは無言で捨てられる。合成クリックは
  ミラーリングウィンドウが**最前面**のときだけ届く（CGEvent は前面アプリにルーティングされる）ため、
  ループは頻繁に再アクティブ化する。
- **キャプチャは `mss` 必須。** `screencapture -l<windowid>` はフォーカスを奪いゲームを PAUSE させる。
  `mss` はフレームバッファ直読でフォーカスを奪わない。
- **座標系は2つ。混同しないこと。** スクショは全ウィンドウなので実測座標は**ウィンドウ相対**で、
  これは `click_window(xf,yf)` で押す。`click_content(xf,yf)` は内容矩形（タイトルバー/レターボックス
  補正）相対で、その系で表した座標専用。Y が内容オフセット分ずれ、きなこパン行とステラ行は近接する
  ため誤った系を使うと誤クリックする。
- **LIFE 回復ポリシー（製品要件・コードで強制）: きなこパンでのみ回復し、ステラは絶対に使わない。**
  `lifeshort` ハンドラはきなこパンの「回復」ボタン（`P_KINAKO_RECOVER`）→確認の×（`P_LIFE_CONFIRM_X`）
  を押す。ステラのボタン座標は意図的にコードに持たせていない。LIFE 不足が `MAX_LIFE_RECOVERS` 回連続
  （きなこパン枯渇）したら、ステラへフォールバックせず**停止**する。
- **ステラ安全 watchdog を随所に。** 盲目連打はしない。未知の明るいダイアログ、閉じられない
  ポップアップ/RANK UP は `STUCK_STOP_SEC` 経過でスクショ保存して停止する（課金ボタンを誤タップ
  しないため）。さらに gameplay（暗い画面）が `GAMEPLAY_TIMEOUT_SEC` を超えて続いたら、
  ミラーリング切断の暗いオーバーレイ等を gameplay と誤認している可能性があるので停止する。
- **PAUSE 再開バグ（修正済み・維持すること）:** `pause_resume.png` は「PAUSE」見出しに一致し、
  ボタンではない。マッチ位置をクリックしても再開しない。PAUSE はテンプレ位置でなく固定の再開位置
  `P_RESUME` をクリックする。
- **ライブ中の自動 PAUSE — 原因特定・解決済み（`_click_screen`）。** iPhone ミラーリングは genuine な
  HID 入力が数秒ないとゲームを PAUSE させる。通常の合成クリック（`source=None`）はゲームには届くが
  アイドル判定をリセットしないため ~4-5秒ごとに PAUSE し、曲が進まなかった。**解決策:**
  `kCGEventSourceStateHIDSystemState` で作ったイベントソースでクリックを送り、各クリック前に
  `CGWarpMouseCursorPosition` で**実カーソルをクリック点へ動かす**（→ `MouseMoved`+`Down`+`Up`）。
  これが genuine 入力扱いとなり **PAUSE 0**、1ライブ≈115秒で完走して連続クリアする（実機確認）。
  ループ中は補助として `caffeinate -dimsu` を起動。**副作用:** 実マウスカーソルがクリック点へ
  ワープし続けるので、実行中は Mac のマウスを操作しないこと。default ソースのパスでは PAUSE は
  防げない（HIDSystemState ソース＋ワープを維持すること）。詳細は `docs/specification.md` §17.6 F
  （§17.6 E は解決前の「回避不能」調査で、F により更新された）。
- **「iPhoneが使用されました」で切断:** iPhone を物理的に触るとミラーリングが終了する。再開には
  `open -b com.apple.ScreenContinuity`（自動再接続。認証不要のことが多い）。切断時の暗い
  オーバーレイは上記 `GAMEPLAY_TIMEOUT_SEC` で検知して止まる。

### 端末非依存（iPhone SE 以外でも自動で動く）

機種でミラーリングウィンドウのサイズ・ゲーム描画アスペクトが変わる（SE≈16:9 / iPhone16≈19.5:9で
全画面・ピラーボックス無し）。**UIの見た目pxサイズは機種でほぼ同じ**だが、**大きいテキスト/ボタン
（NEXT/Result 等）は機種で拡大**され、要素位置も変わる。対応方針:

- **ダイアログのボタンは「テンプレのマッチ位置＋固定pxオフセット」**(anchor-offset。`click_anchor`
  と `ANCH_*` 定数)。クリック位置が画像マッチに追従するので中央配置を仮定せず堅牢・機種非依存。
  `ANCH_*` は SE実測の (ボタン位置−マッチ中心) で、SEでは元座標を完全再現（回帰維持）。
  ※「N回復しました」確認の×・Result中央送り・menu安全タップは直後/非ボタンのため中央
  オフセット(`click_center_off`/`OFF_*`)のまま。
- **全画面ボタン（START/NEXT/申請する）はテンプレのマッチ位置を直接クリック**（`click_match`）。
- **カード型ポップアップ（報酬獲得/アイテム獲得/RANK UP 等）の×は色検出**（`detect_card_x`：
  シアン→グリーンのヘッダ帯を検出し右上の×を特定）＝テンプレ/座標非依存。`cardx` 状態。
- **テンプレは機種別バリアントを併用**: `load_templates` が `<stem>.png` に加え `<stem>_*.png`
  （例: `song_select_16.png`, `result_title_16.png`）も読み、`match_best` がどれか当たればよい
  （拡大で転用できないテンプレは機種版を撮り足す＝自動）。`SCALES` も ±20% に拡張。
- 未知画面では**クリックせず安全停止**（`menu` 状態。誤爆の連鎖を防止）。
- フレンド選択は `アピールスキル` ラベル（=行内）のマッチ位置をタップして選択。
- タップ円は `CIRCLES`（内容矩形相対）をスケール（iPhone16でも命中良好。円自動検出は未実装）。

テンプレ取得: `driver.py shot`/`clickshot` でネイティブ解像度クロップ。しきい値は `TEMPLATES`、
オフセットはファイル先頭付近の定数（`ANCH_*`, `OFF_*`, `CLOSEX_OFFSETS`）。ESCキルスイッチは
誤検出デバウンス（2回連続検出で停止）。
