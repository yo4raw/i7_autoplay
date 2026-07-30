# 当初設計（未実装・履歴）

> このファイルは実装前（2026-06-04）に書かれた設計で、**実装されていない**。
> 実態は [`../README.md`](../README.md) から辿ること。
> ここに書かれた OCR・設定ファイル・ログ／CLI 仕様・プロジェクト構成は現在のコードに存在しない。

## 8. OCR 仕様

### 8.1 読取り対象
- スタミナ残量（例: `120/120`）
- 累計pt（停止条件判定・任意）
- 周回/挑戦回数表示（あれば）

### 8.2 OCR エンジン・前処理
- エンジン: **Apple Vision（`ocrmac` 経由、言語 `jpn`）**。横書き数値に強く、追加バイナリ不要。
- 前処理: 対象 ROI をクロップ → 必要に応じ拡大・二値化・コントラスト調整。

### 8.3 認識結果の検証
- 正規表現で数字（および `/` 区切り）を抽出。
- 桁数・値域チェック（例: スタミナは 0〜上限、負値や桁あふれは無効として再取得 or テンプレ判定にフォールバック）。
- 可能な限り **テンプレ判定を優先** し、OCR は数値が必要な箇所に限定する。

---

## 9. 設定ファイル仕様

### 9.1 形式・配置
- 形式: **YAML**（既定）。配置: 既定 `config/default.yaml`、`--config` で上書き可能。
- 読込時に `pydantic` でスキーマ検証し、エラーは分かりやすく報告。

### 9.2 設定項目一覧
| キー | 型 | 既定 | 説明 |
|------|----|------|------|
| `target_loop_count` | int | 必須 | 目標周回数。到達で SAFE_STOP |
| `max_retries` | int | 3 | RECOVERY のリトライ上限。超過で ERROR_STOP |
| `max_consecutive_errors` | int | 5 | 連続エラー上限 |
| `template_dir` | str | `./assets/templates` | テンプレ画像ディレクトリ |
| `match_threshold` | float | 0.85 | テンプレマッチ相関閾値（0–1） |
| `action_delay` | float | 0.5 | クリック後の最小待機（秒） |
| `poll_interval` | float | 0.5 | 画面ポーリング間隔（秒） |
| `timeouts.default` | float | 15 | 状態別タイムアウト既定（秒） |
| `timeouts.live_playing` | float | 180 | AUTO 進行待ちタイムアウト（楽曲尺＋余裕） |
| `timeouts.<state>` | float | - | 各状態の個別上書き（任意） |
| `stamina.recover_enabled` | bool | true | スタミナ自動回復 ON/OFF |
| `stamina.item` | str | `drink_s` | 使用アイテム識別子（テンプレ名に対応） |
| `stamina.max_recover_per_loop` | int | 3 | 1周回あたり回復試行上限 |
| `stop_on_item_depletion` | bool | true | アイテム枯渇で停止するか |
| `target_event_points` | int\|null | null | 累計pt 目標（OCR、到達で停止／null で無効） |
| `live.difficulty` | str | `normal` | 選択する難易度 |
| `live.song` | str\|null | null | 選択楽曲（null で固定/先頭） |
| `use_play_again` | bool | true | 「もう一度」ショートカットを使うか |
| `log.level` | enum | `INFO` | DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `log.file` | str | `./logs/autoplay.log` | ログファイルパス |
| `log.rotate_mb` | int | 10 | ローテーションサイズ（MB） |
| `log.save_debug_captures` | bool | false | 誤検出解析用スクショ保存 |
| `mirroring.window_title` | str | `iPhone Mirroring` | 対象ウィンドウ名（`iPhoneミラーリング` も内部で照合） |
| `mirroring.expected_resolution` | [int,int]\|null | null | 期待ウィンドウサイズ（ずれ検出用） |
| `kill_switch.hotkey` | str | `cmd+shift+q` | 緊急停止ホットキー |

### 9.3 設定例（`config/default.yaml`）
```yaml
target_loop_count: 50
max_retries: 3
max_consecutive_errors: 5

template_dir: ./assets/templates
match_threshold: 0.85
action_delay: 0.5
poll_interval: 0.5

timeouts:
  default: 15
  live_start: 30
  live_playing: 180
  result: 20

stamina:
  recover_enabled: true
  item: drink_s          # assets/templates/stamina/drink_s.png に対応
  max_recover_per_loop: 3

stop_on_item_depletion: true
target_event_points: null   # 例: 500000 で累計pt到達停止

live:
  difficulty: normal
  song: null

use_play_again: true

log:
  level: INFO
  file: ./logs/autoplay.log
  rotate_mb: 10
  save_debug_captures: false

mirroring:
  window_title: iPhone Mirroring
  expected_resolution: null   # 例: [402, 874]

kill_switch:
  hotkey: cmd+shift+q
```

---

## 10. ログ仕様
- 出力先: **stdout ＋ ファイル**（`log.file`、サイズローテーション `log.rotate_mb`）。
- レベル: DEBUG / INFO / WARNING / ERROR / CRITICAL（`log.level` で制御）。
- フォーマット: タイムスタンプ・レベル・**状態名**・アクション・認識スコア等を含む。
  例: `2026-06-04 12:00:00 INFO [S9 LIVE_PLAYING] result_marker matched score=0.93`
- デバッグキャプチャ: `log.save_debug_captures=true` で、ERROR 時や認識失敗時に画面スクショを保存。
- 停止時サマリ: 実行周回数・使用アイテム数・経過時間・停止理由を INFO で出力。

---

## 11. エラーハンドリング・リトライ方針
- **検知してから操作**（blind sleep を避ける）: 各ステップは「キャプチャ→期待アンカー一致→操作」。
  固定待機は焦点切替後の settle（約 200ms）程度に限定し、待機は **poll-until-condition**。
- **再認識リトライ**: マッチ失敗は再キャプチャで K 回リトライ → 既知の「閉じる/戻る」へフォールバック → 再アンカー。
- **不明画面の復帰（S14）**: `back_button`/`home_button` を順に試し、ホーム経由で再スタート。
- **焦点/Space 喪失**: 毎サイクルで最前面アプリを確認し、ミラーリングでなければ再 `activate`。
  ウィンドウが見つからない（アプリ終了・別 Space・iPhone 切断）場合は一時停止し明示メッセージ。
- **iPhone スリープ/黒画面**: 黒フレームへ連打しない。待機→復帰試行→不能なら SAFE_STOP。
- **連続エラー上限**: `max_consecutive_errors` 超過で ERROR_STOP（最終スクショ保存）。

---

## 12. CLI 仕様
- エントリポイント: `i7autoplay`（`typer` ベース）。
- サブコマンド:
  - `i7autoplay run` — 周回を実行。
  - `i7autoplay doctor` — 権限（画面録画・アクセシビリティ）とウィンドウ検出を診断。
  - `i7autoplay calibrate` — テンプレ取得補助・座標/スケール確認（既知点にマーカー描画）。
- 主なオプション:
  - `--config PATH`（設定ファイル）
  - `--dry-run`（実クリックせず FSM 遷移とクリック予定をログ出力）
  - `--target N`（`target_loop_count` 上書き）
  - `--log-level LEVEL`

---

## 14. 開発フェーズ・マイルストーン（実装ロードマップ）

### 14.2 プロジェクト構成（実装フェーズで作成）
```
i7_autoplay/
├── pyproject.toml              # 依存・console_script: i7autoplay
├── README.md                   # セットアップ/権限/ウィンドウサイズ固定
├── config/default.yaml
├── assets/templates/{live,stamina,popups}/*.png
├── src/i7_autoplay/
│   ├── cli.py                  # typer: run / doctor / calibrate
│   ├── config.py               # pydantic + YAML
│   ├── permissions.py          # 画面録画/アクセシビリティ確認
│   ├── window.py               # ミラーリングウィンドウ検出・bounds・scale
│   ├── capture/{base,mss_capturer,sck_capturer}.py
│   ├── geometry.py             # 座標変換（唯一の真実・要単体テスト）
│   ├── recognition/{matcher,ocr,templates}.py
│   ├── actuator/{focus,input}.py   # 最前面化 + CGEvent tap/swipe
│   ├── states/{machine,context,handlers/*}.py   # FSM
│   ├── safety.py               # キルスイッチ・ウォッチドッグ
│   └── logsetup.py
└── tests/{test_geometry,test_config,test_matcher}.py + fixtures/
```

### 14.3 マイルストーン
1. **PoC**: キャプチャ＋座標変換＋権限チェック（既知点にマーカー描画して検証）。
2. **入力**: actuator で既知 UI 要素へのタップ成功（最前面化込み）。
3. **認識**: matcher ＋ calibration モードでテンプレ一式を取得。
4. **OCR**: スタミナ/周回数の読取り。
5. **FSM**: 周回 → ポップアップ → スタミナ → 停止条件を配線。
6. **安定化**: safety / cli / config / ログ / テスト。

### 14.4 主要・高リスクモジュール
- `geometry.py` — Retina/座標変換、最もバグが潜む（単体テスト必須）。
- `actuator/input.py` — 最前面化必須の CGEvent 入力、プラットフォーム制約の核。
- `window.py` — `iPhone Mirroring` / `iPhoneミラーリング` ウィンドウ検出。
- `states/machine.py` — 周回/ポップアップ/スタミナ/停止を統括する FSM。

---

