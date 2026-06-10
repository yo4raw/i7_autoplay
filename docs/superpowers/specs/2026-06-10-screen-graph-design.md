# 画面グラフ・データ駆動化 設計書

日付: 2026-06-10 / 対象端末: iPhone SE（採取基準機）、iPhone 16（バリアント）
ステータス: ユーザー承認済み設計（実装計画は未着手）

## 1. 背景と目的

autolive の無人運用はイレギュラー（未知画面・迷子状態）に弱く、現状は「未知画面→安全停止」
で人手の復帰待ちになる。本プロジェクトでは:

1. 実機を探索して**全画面の仕様・遷移図・識別テンプレ（アイコン切り抜き）**を整備し、
2. それを**機械可読な画面グラフ（screens.yaml）**として保存し、
3. autolive を**画面グラフを解釈するデータ駆動エンジン**に書き換える（案A・ユーザー選択）。

迷子状態からの自動復帰（復旧ナビ）を実現し、新画面対応をデータ追加だけで行えるようにする。

## 2. ゴールと非ゴール

**ゴール**
- 画面カタログ（人間用 Markdown + Mermaid 遷移図、自動生成）
- テンプレ資産ツリー `assets/screens/`（全画面スクショ原本＋切り抜き、機種バリアント）
- 機械可読データ `data/screens.yaml`（検出・アクション・遷移・安全区分・機種別座標）
- データ駆動実行エンジン（復旧ナビ込み）への移行と検証

**非ゴール**
- ライブ打鍵エンジンの変更（timing/ROI/keepalive/PAUSE対策は無傷で維持）
- ノーツ種別対応（フリック/ロング/スライド）
- ゲーム全画面の網羅（復旧経路＋危険画面の識別のみ。§7参照）

## 3. 安全ポリシー（エンジン強制・データで上書き不可）

- **ステラ消費・課金・ガチャ実行は構造的に不可能にする**: `kind: danger` の画面では
  back 系アクション以外をエンジンが拒否。lifeshort 画面で許可されるのはきなこパン回復系のみ。
- きなこパン使用は許可。`MAX_LIFE_RECOVERS` 連続で LIFE 不足が続いたら停止（在庫切れ＝ステラに
  フォールバックしない）。
- 未知画面→クリックせず安全停止（`STUCK_STOP_SEC`）。`GAMEPLAY_TIMEOUT_SEC` /
  `RESULT_STUCK_SEC` / ESC キルスイッチ（2回デバウンス）はすべて維持。
- 復旧ナビ中に同一画面を3回再訪したら経路不全とみなしスクショ保存＋停止。
- **他機種の座標を流用して推測クリックしない**（§5）。
- **周回ポリシー: 必ず EASY、ブースト OFF**。楽曲選択でブーストON検出テンプレに当たったら
  OFF 化してから NEXT（恒久ユーザー要件）。

## 4. アーキテクチャ（3層）

```
┌─ data: 画面グラフ (data/screens.yaml) ───────────────┐
│ 画面定義 = 検出テンプレ + アクション + 遷移先 + 安全区分     │
├─ assets: テンプレ資産 (assets/screens/<画面id>/) ──────┤
│ 全画面スクショ原本 + アイコン/ボタン切り抜き（機種バリアント込）│
├─ engine: 汎用実行エンジン (tools/autolive.py 改) ──────┤
│ YAML を読み、検出→グラフ上の現在地特定→目標へ行動選択       │
└────────────────────────────────────────┘
```

**コードに残すもの（回帰リスク対策の核）**
- ライブ打鍵エンジン（`handler: gameplay` としてグラフから参照されるだけ）
- アクションプリミティブ: `click_match` / `click_anchor` / `click_fixed`（機種別座標）/
  `card_x`（色検出）/ `handler:`（組み込み動作）
- 安全インバリアント（§3）と各種カウンタ（ループ数・LIFE回復回数）

## 5. データ形式 `data/screens.yaml`

```yaml
devices:                      # 機種プロファイル（起動時に内容矩形アスペクト比で自動判別）
  se:       { label: iPhone SE,  content_aspect: 1.78 }   # ≈16:9
  iphone16: { label: iPhone 16, content_aspect: 2.16 }   # ≈19.5:9

screens:
  - id: songselect
    name: 楽曲選択
    kind: loop          # loop=周回経路 / nav=復旧経路 / dialog=ポップアップ
                        # / danger=認識のみ / system=iOS系
    detect:
      template: next_btn      # assets/screens/songselect/next_btn*.png（変種込み照合）
      threshold: 0.85
      brightness: bright      # bright / dark / any（明るさゲート。省略時は any）
    priority: 110             # 判定順（現行 FSM の固定順序を数値で保存）
    actions:
      select_easy:  { type: click_anchor, template: easy_tab, offset: [0, 0] }
      boost_off:    { type: click_match,  template: boost_on }   # ON表示を押してOFF化
      go_next:      { type: click_match,  template: next_btn }
    loop_action: [select_easy, boost_off?, go_next]   # ?=検出された時のみ
    edges:
      - { action: go_next, to: friendselect }
    notes: |
      ブーストは必ずOFF。boost_on テンプレが当たる間は go_next を押さない。

  - id: pause
    kind: dialog
    detect: { template: pause_title, threshold: 0.78, brightness: dark }
    priority: 10
    actions:
      resume:
        type: click_fixed
        pos:                  # 窓相対 0..1。機種キー必須（裸の座標はローダが拒否）
          se:       [0.69, 0.76]
          iphone16: [0.715, 0.775]
    edges:
      - { action: resume, to: gameplay }

  - id: shop
    kind: danger              # 認識のみ。back 系以外のアクションはローダ/エンジンが拒否
    detect: { template: id_anchor, threshold: 0.85 }
    actions:
      back: { type: click_match, template: back_arrow }
    edges:
      - { action: back, to: home }
```

**機種別座標の規約**
- `click_fixed` の `pos` は必ず機種キー付き辞書。裸の `[x, y]` はバリデーションエラー。
- 現在機種のエントリが無い場合、そのアクションは「利用不可」。テンプレ系の代替アクションが
  あればそれを使い、無ければ安全停止。**他機種の座標で推測クリックは絶対にしない**。
- anchor-offset の `offset` は SE 実測 px（マッチ位置に追従するため機種非依存。現行 `ANCH_*` と
  同思想）。機種で offset が異なる事例が出たら `offset` も機種キー辞書を許容する。
- 機種判別は内容矩形のアスペクト比で自動（SE≈1.78 / iPhone16≈2.16 は明確に分離）。
  `--device se` で手動上書き可。

## 6. テンプレ資産規約 `assets/screens/`

```
assets/screens/
  songselect/
    _full.png             # 画面全体スクショ（SE・文書/再取得用の原本）
    _full.iphone16.png    # 機種別の全画面（あれば）
    id_anchor.png         # 画面識別用の切り抜き（detect が参照）
    next_btn.png          # ボタン/アイコン切り抜き（actions が参照）
    next_btn.iphone16.png # 機種バリアント（照合は全バリアント試行＝機種非依存）
  shop/
    _full.png
    id_anchor.png         # danger 画面は識別アンカー＋back だけで良い
    back_arrow.png
```

- 切り抜きは**ネイティブ解像度・無加工**（`driver.py shot` の原寸から crop）。
- `_full.png` を必ず残す: 別機種・イベント装飾でテンプレが崩れた際に原本から切り直せる
  （過去の「イベント装飾でテンプレ崩れ→停止」問題への備え）＋仕様書の図版になる。
- 命名: `<stem>.png`（SE 基準）/ `<stem>.<機種>.png`。照合は `<stem>*.png` 全部を試す
  （現行 `load_templates` のグロブ規約を踏襲、手動切替なし）。
- 既存 `assets/templates/` は移行完了まで触らない（現行コードが参照中）。移行後に新ツリーへ吸収。

## 7. 探索プロセス（実機の触り方）

`driver.py` で SE 実機を巡回。1画面ごとの定型手順:

1. `driver.py shot` で全画面取得 → `_full.png` 保存
2. 識別アンカー（画面タイトル/固有アイコン）とボタン類を crop
3. ボタンを実際に押して遷移先を確認 → `edges` に記録 → 戻る
4. screens.yaml にエントリ追記

**探索中の安全ルール**: ステラ・課金・ガチャ実行は一切踏まない。danger 画面では戻る系のみ
タップ。きなこパン使用・ライブ消化は許可済み。編成・デッキ編集は探索するが、周回用編成を
壊さないことを確認してから戻る。各タップ前にスクショで対象を目視確認（盲目クリックしない）。

**巡回範囲**: ホーム→イベント→楽曲選択→フレンド→編成→ライブ→リザルト系の全経路、
ライフ回復ダイアログ、デッキ編集、識別のみの danger 画面群（ショップ/ガチャ/お知らせ等）、
既知ポップアップ類（既存テンプレから流用可能なものは流用）。

**周回と並行できる採取**: mss キャプチャはフォーカスを奪わないため、autolive 周回中に
パッシブ観測プロセスを並走させ、周回経路上の画面スクショ（コーパス＋ `_full.png` 原本）を
収集できる。経路外（ホーム/ショップ等）の探索のみ周回の中断が必要。

## 8. 仕様書の自動生成 `docs/screens.md`

`tools/gen_screen_docs.py` が screens.yaml から生成:

- 冒頭に Mermaid 画面遷移図（edges から生成、loop 経路を強調）
- 画面ごとのセクション: スクショ（`_full.png` 参照）、識別方法、アクション一覧
  （機種別座標も表示）、遷移先、安全区分
- 手書きの注意書きは screens.yaml の `notes:` に書き、生成文書へ流し込む（文書とデータの乖離防止）

既存 `docs/specification.md` は現行 FSM の記録として残し、冒頭に相互参照を追記。

## 9. 実行エンジン

メインループは現行同様 **capture → detect → act**:

1. **detect**: 明るさゲート → `priority` 順に各画面の detect テンプレを照合
   （現行の固定判定順 pause→gameplay→lifeshort→… を数値で完全再現）。不一致なら `unknown`。
2. **現在地と目標の比較**: `kind: loop` の画面なら `loop_action` を実行。経路外
   （nav/danger）なら**復旧モード**: edges を BFS して songselect への最短経路の次の一手を実行。
3. **act**: アクションプリミティブを実行。

**コード構成**（追加は2ファイルに留める）:
- `tools/screen_graph.py`（新規）— YAML ローダ＋バリデーション＋機種判別＋BFS。純粋ロジックで
  テスト可能。
- `tools/autolive.py`（改修）— elif 14連の状態分岐を screens.yaml 解釈に置換。打鍵エンジン・
  PAUSE 対策・watchdog・きなこパンポリシー・カウンタは現行コード無傷で `handler:` 参照。

## 10. 移行手順（並走→検証→切替）

1. **並走**: `--brain legacy|data` フラグ新設、既定 `legacy`。data ブレインを実装し、現行14状態を
   screens.yaml に忠実移植（テンプレ・閾値・判定順そのまま）。
2. **検証**:
   - **検出パリティテスト（本リポジトリ初の自動テスト）**: `tests/corpus/<画面id>/*.png` に
     ラベル付きスクショを保管（探索・周回観測で採取）。新エンジンの分類が全コーパスで
     ラベルと一致することを確認。
   - 実機 dry-run（`--dry-run --brain data` で判定ログ比較）→ 実機10周
     （PAUSE 0・周回タイム・きなこ回復動作が legacy と同等）。
3. **切替**: 既定を `data` へ。legacy はフラグで1〜2週間残し、問題なければ削除
   （2ブレイン恒久併存はしない）。

## 11. エラー処理・テスト

**ロード時バリデーション（起動前に全部弾く）**: 機種キーなしの裸座標、存在しないテンプレ参照、
未知画面への edge、danger 画面に back 以外のアクション、未知のアクション型 → 明確なエラーで
起動拒否。

**実行時**: 未知画面→ `STUCK_STOP_SEC` でスクショ保存＋停止。復旧ナビの同一画面3回再訪→停止。
既存 watchdog 群・ESC デバウンスは全維持。

**テスト**: ①検出パリティコーパス ② screen_graph.py ユニットテスト（バリデーション・機種判別・
全 nav ノードから songselect への BFS 到達） ③ docs 生成スクリプトの実行確認。

## 12. リスクと対策

| リスク | 対策 |
|---|---|
| FSM 書き換えによる周回回帰 | 打鍵エンジン等は無傷維持・`--brain` 並走・パリティコーパス・実機10周検証 |
| 機種差で座標がずれ誤クリック | 座標は機種キー必須＋未定義機種では利用不可＋テンプレ優先 |
| イベント装飾でテンプレ崩れ | `_full.png` 原本保管で切り直し容易化・バリアント照合 |
| 復旧ナビの無限ループ | 同一画面3回再訪で停止 |
| 探索中の誤タップ（ステラ等） | danger 区分のアクション制限＋タップ前の目視確認手順 |
