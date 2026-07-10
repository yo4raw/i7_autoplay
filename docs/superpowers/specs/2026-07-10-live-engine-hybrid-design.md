# ライブ中自動操作の刷新: ハイブリッド方式（roi発火 × track種別先読み）設計書

日付: 2026-07-10 / 対象: `tools/autolive.py`, `tools/note_engine.py`

## 1. 目的

「自動操作の安定」を4観点で改善する。

1. **周回が止まらない** — 実績あるタイミング系・安全装置を一切変えない（新機能は既定OFF）
2. **MISS/BAD削減** — 緑ホールド（チェーン尻尾の取りこぼし）対応、種別先読みの一般化
3. **機種非依存** — タップ円の自動キャリブレーション（実測: 精度不良の主因は CIRCLES ズレ）
4. **保守性** — 新ロジックは独立モジュール＋合成フレームによるユニットテストを整備

制約: **完全反応型のみ**（曲ごとの準備走行・譜面学習はしない。ユーザー確認済み）。

## 2. 方針（承認済み・案B ハイブリッド）

- 打鍵の「**いつ**」= 現行 roi スパイク検出（`_gameplay_timing`）を温存。
  lead=0.025 で較正済み・MISS 45→14→3 まで実機で追い込んだ資産を捨てない。
- 打鍵の「**なに**」= `note_engine.Tracker` を並走させ、スポーン側で得た色種別を
  レーン別に先読みする **TypeForecast** を新設。現行 `_approach_red`（赤だけの
  到達直前検色）の一般化。
- roi 発火時に forecast を参照して出し分け:
  - `red` → フリック（既存 `_flick`）
  - `green` → ホールド開始（§4）
  - `blue` → 当面タップ（スライドは将来課題。頭だけ＝現状と同じ部分点）
  - `white` / 予報なし / 予報が古い → タップ（現行動作）
- **フェイルソフト**: track が不調でも現行動作（全タップ＋`--flick` 赤フリック）に
  自然に劣化する。予報は「あれば使う」情報で、発火条件には関与しない。

## 3. コンポーネントと変更範囲

| ファイル | 変更 |
|---|---|
| `tools/note_engine.py` | `TypeForecast` クラス追加。`Tracker`/`assign_lane` に `lanes` 引数を追加（既定は現行値）。円自動検出 `detect_circles()` 追加。**LANES 既定値を補正後 CIRCLES（右2円ズレ補正 2026-06-07）に同期** |
| `tools/autolive.py` | `--predict` / `--auto-circles` フラグ追加（**両方とも既定OFF**）。`_gameplay_timing` に forecast 参照とホールド解除の ETA 化を追加（`--predict` 時のみ）。gameplay 突入時の円キャリブレーション（`--auto-circles` 時のみ）。Tracker/forecast へは autolive の `CIRCLES` を渡す（定数の二重管理を解消） |
| `tests/` | 合成フレームによるユニットテスト＋実フレームコーパス（`tests/corpus_raw/`、リポジトリ外扱い・あればスモーク）|
| ドキュメント | `docs/specification.md` §17 追記、`CLAUDE.md` 更新 |

**やらないこと（明示的スコープ外）**:
- 実績コード（roi 発火・FSM・メニュー処理・keepalive・watchdog・ステラ安全・supervisor）の
  移設や書き換え。1200行の `autolive.py` の本格分割は、本PRの実機検証が済んでから別PRで行う。
- 青スライドのジェスチャ実装（単一カーソル制約＋実機検証が必要なため TODO として明記）。
- メニュー側の固定座標テンプレ化（`P_EASY_TAB` 等）。新テンプレの実機撮影が必要なため別途。

## 4. TypeForecast 仕様

- 入力: roi エンジンが取得済みのフレーム（**追加キャプチャなし**）。毎フレーム
  `detect_notes()` → `Tracker.update()` を回す。
- track が `is_note` かつ `lane >= 0` になった時点でレーン別キューに登録:
  `(track_id, type, eta, last_seen)`。同一 id は最新情報で更新。
- `forecast.peek(lane, now)` → そのレーンで到達が最も近い track の種別と ETA。
  `last_seen` が `STALE_SEC`(0.6s) より古い項目は破棄（誤予報でジェスチャ誤爆しない）。
- roi 発火時に `forecast.consume(lane, now)` で取り出し（1ノーツ1予報）。

### 緑ホールドの解除条件（旧 `--holds` の失敗要因を回避）

単一カーソル制約: 合成マウスは1個なので、**ホールド中は他レーンを叩けない**
（現行 `--holds` も同じ）。EASY 譜面ではホールド中の並行ノーツは稀で、
チェーン尻尾の MISS 削減のほうが利得が大きい。

- 開始: roi 発火 × 予報 `green` → その円で押下保持（保持中は `move` を送り続け
  genuine 入力を維持＝PAUSE 防止、既存パターン）。
- **解除: 「保持中の輝度持続」には依存しない**（タップ波紋と交絡して失敗した旧方式）。
  代わりに forecast が知っている**同レーン次ノーツの ETA 予測時刻で解除**する
  （毎フレーム track の進行で更新）。次ノーツの track が見えない場合や
  `HOLD_MAX_SEC` 超過では必ず解除（安全上限は従来どおり）。
- 保持中は当該円のベースライン更新を停止（解除直後の誤発火防止に
  `NOTE_DEBOUNCE_SEC` を適用、従来と同じ）。

## 5. 円自動キャリブレーション（`--auto-circles`）

- gameplay 突入時（state が gameplay に遷移した最初の数フレーム）に実施:
  下帯（content 相対 y 0.50–1.00）で `cv2.HoughCircles`（明るいリング）を検出。
- 検出円を現行 `CIRCLES`（事前分布）へ最近傍マッチ。**4円すべてが許容誤差
  （content 相対 0.06）内で一致したときだけ置換**。1つでも欠けたら現行値を維持して
  ログに残す（誤検出で悪化させない）。
- 置換は「そのライブ実行中」のみ（プロセス内）。`ARC_CENTER` は変更しない。
- オフライン検証 CLI: `python tools/note_engine.py circles <frame.png> [out.png]`
  （検出円と prior をオーバーレイ描画）。

## 6. テスト方針

依存を増やさず `unittest`（標準ライブラリ）で書く。合成フレーム
（黒地に白/色ブロブ・リング）を numpy で生成し、実機なしで検証できるようにする。

- `tests/test_note_engine.py` — `detect_notes` / `classify_color` / `assign_lane` /
  `Tracker`（移動ブロブの track 化・静止物除外・レーン/ETA 推定）
- `tests/test_type_forecast.py` — 登録/peek/consume/stale 破棄/レーン分離
- `tests/test_autocal.py` — 合成リング4円の検出・prior マッチ・部分検出時のフォールバック
- `tests/test_corpus_smoke.py` — `tests/corpus_raw/gameplay/*.png` があれば
  `detect_notes`/`detect_circles` を全フレームに通してクラッシュしないこと（無ければ skip）
- 実行: `.venv/bin/python -m unittest discover tests`

## 7. リスクと対策

| リスク | 対策 |
|---|---|
| 新ロジックの回帰で周回が止まる | `--predict`/`--auto-circles` は**既定OFF**。OFF時のコードパスは現行と同一 |
| 予報誤り（種別誤認）でジェスチャ誤爆 | stale 破棄(0.6s)・予報なし→タップ・ホールドは `HOLD_MAX_SEC` 上限 |
| Hough の誤検出で円がズレる | 4円完全一致＋許容誤差内のみ採用、失敗時は現行値へフォールバック |
| ホールド中の並行ノーツ MISS | 単一カーソル制約として容認（EASYでは稀）。設計に明記 |
| track の CPU 負荷でフレームレート低下 | detect_notes は上帯のみの連結成分抽出（軽量）。実機で fps をログ確認する手順を PR に記載 |

## 8. 実機検証手順（PR マージ前にユーザーが実施）

1. 従来動作の無回帰確認: フラグなしで1ライブ（現行と同じ挙動のはず）
2. 予報精度の観測: `python tools/note_engine.py live 120`（読み取り専用）で
   種別・レーン・ETA のログを目視確認
3. `--predict` で1〜3ライブ走行し、リザルト（MISS/BAD/COMBO/SCORE）を現行と比較
4. `--auto-circles` で開始時ログの検出円座標を確認（`circles` CLI でオーバーレイ可）
5. 問題なければ supervisor の起動引数に反映（別コミット）

## 9. 将来課題（本PRではやらない）

- 青スライド（次の青までスライド長押し）のジェスチャ実装と実機検証
- `autolive.py` 本体のモジュール分割（FSM / 画面分類 / I/O）
- メニュー固定座標（`P_EASY_TAB` 等）のテンプレ化（実機でテンプレ撮影が必要）
- 未知画面停止時の変種テンプレ追加ヘルパー
