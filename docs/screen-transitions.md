# 画面遷移仕様書（Screen Transitions）

本書は **実機（iPhone SE / iPhone ミラーリング, 671×348）で autolive を長時間（160回超クリア）
運用しながら観測**した、累計イベント周回中の**具体的な画面遷移**をまとめたもの。
旧 `docs/specification.md`（現 [`architecture.md`](architecture.md)）にあった設計時の FSM 概念仕様（S0〜S16）も本書の付録Aに集約した。
**挙動を変える前に本書と [`README.md`](README.md) 索引が指す各ドキュメントの両方を読むこと。**

> **[`screen-flow.md`](screen-flow.md) との使い分け**: 本書は**実機で観察した記録**
> （どの画面がどう見えたか、座標はいくつだったか）。`screen-flow.md` は**実装から抽出した
> 現在の仕様**（どの状態をどの順で判定し、何をするか）。実装を変えたら更新するのは
> `screen-flow.md` のほうで、本書は観察が増えたときに追記する。

> 凡例: 座標は特記なき限り **ウィンドウ相対 (0..1)**。「アンカー」はテンプレのマッチ位置＋
> 固定pxオフセット（画像追従・端末非依存）。「中央オフセット」はゲーム中央＋固定pxオフセット。

---

## 1. 1周（1クリア）の標準フロー

連戦（連続ライブ再プレイ）で回る通常ループ。**ホーム画面は経由しない。**

```text
[編成/楽曲選択]
   └─ START / (EASY選択→NEXT→フレンド選択→編成→START)
        ↓
[ライブ中 gameplay] ── 約115秒・ノーツ打鍵（keepaliveでPAUSE防止）
        ↓
[per-song Result]（小文字青「Result」）── 画面中央タップで送る
        ↓
[EVENT RESULT]（緑「-EVENT RESULT-」）
   ├─ 「申請する」ボタンあり → friendreq でタップ（＝ここでクリア計上）
   ├─ 報酬ポップアップ（カード型）→ cardx で×クローズ（複数回）
   └─ 申請後の EVENT RESULT（申請ボタン消失）→ eventresult で中央タップ
        ↓
[（LIFE不足なら）ライフが足りません] → きなこパンで回復（ステラ厳禁）
        ↓
[連続ライブ再プレイ？] → 「はい」で同曲を再開（次ループへ）
        │
        └─（連戦終了時）→ [楽曲選択] → EASY選択 → NEXT
                              → [フレンド選択] → [編成] → START → 次ライブ
```

実機観測のフレーム比（あるセッション・118クリア時点）:

- gameplay 130,846 / result 489 / **eventresult 216** / cardx 184 / friendreq 94
- **lifeshort 65** / menu 39 / friendselect 30 / songselect 19 / formation 18

→ result系（per-song 489 ＋ EVENT RESULT 216）と cardx・lifeshort が毎周必ず通過する主要画面。

---

## 2. 状態の判定順序（detect()）

**順序が重要**。先にマッチした状態を採用する。誤検出が後段の正しい状態を隠す／隠されるのを防ぐ
ため、専用ダイアログ → 汎用ポップアップ → 送り画面の順に並べる。

| #  | 状態          | 判定方法                                    | 補足 |
| -- | ------------- | ------------------------------------------- | ---- |
| 1  | pause         | `pause_resume.png`(0.78)                     | 暗背景でも確実。**見出し**にマッチするので固定の再開位置を押す |
| 2  | gameplay      | 明るさ < `DARK_THRESH`(65)                   | ライブ中（暗画面） |
| 3  | lifeshort     | `life_short.png`/`life_short_event.png`(0.85)| LIFE不足。最優先で判定（ステラ誤押し防止） |
| 4  | friendreq     | `friendreq_yes.png`(0.74)                    | EVENT RESULT の「申請する」。クリア計上 |
| 5  | replay        | `replay_title.png`(0.82)                     | 連続ライブ再プレイ確認の見出し |
| 6  | rankup        | `rankup.png`(0.78)                           | RANK UP!（×フォールバック用） |
| 7  | dldialog      | `dl_dialog.png`(0.85)                        | データDL確認 |
| 8  | story         | `story_dialog.png`(0.85)                     | ストーリー遷移確認 → いいえ |
| 9  | **formation** | `formation.png`(0.85)                        | **START明確なら編成と確定**（cardx色検出より先に判定。§5.2） |
| 10 | cardx         | 色検出 `detect_card_x`                        | カード型ポップアップのシアン→緑ヘッダ帯から×位置を特定 |
| 11 | closex        | `close_x.png`(0.87)                          | カード右上×（候補オフセット巡回） |
| 12 | **eventresult** | `eventresult_title.png`(0.85)              | **EVENT RESULT 見出し**（§5.1） |
| 13 | result        | `result_title.png`(0.55)                     | per-song「Result」 |
| 14 | songselect    | `song_select.png`(0.85)                      | NEXTボタン。**EASY選択を挟む**（§4） |
| 15 | friendselect  | `friend_select.png`(0.85)                    | 「アピールスキル」ラベルで行選択 |
| 16 | formation(再) | `formation.png`(0.85)                        | result後の通常順での編成判定 |
| 17 | menu          | 上記いずれも不一致                            | **未知画面＝クリックせず安全停止**（誤爆防止） |

---

## 3. 各画面の詳細（見た目・アクション・座標）

### 3.1 ライブ中（gameplay）

- 見た目: 暗い演奏画面。COMBO/SCORE表示、下部に判定円。
- アクション: timing検出でノーツ到達時にタップ。ノーツ無し区間は keepalive で genuine 入力を
  出し続け **PAUSE を防ぐ**（HIDSystemStateソース＋カーソルワープが必須。詳細は
  [`device-findings.md`](device-findings.md) の「PAUSE の解決策（2026-06-05）」）。
- 所要: PAUSE解決後 約115〜125秒/曲。

### 3.2 per-song Result

- 見た目: **小文字「Result」**（淡い青背景）。キャラEXP・ハート等。
- アクション: `result` → 画面中央タップ（`OFF_RESULT_ADV`）で送る。

### 3.3 EVENT RESULT（イベント集計リザルト）

- 見た目: **緑・大文字斜体「-EVENT RESULT-」**。S/SSグレード、スコア、難易度「EASY✦」、
  MANUAL、グレードPt、合計P/累計P、右にフレンドカード。**KEEP OUT テープがイベント装飾で重なる。**
- 2段階ある:
  1. **申請する ボタンあり** → `friendreq`(0.74) でボタンを直接タップ。**ここでクリア計上**。
  2. **申請後（ボタン消失）** → `eventresult`(0.85) で画面中央タップして送る。
- 注意: per-song「Result」テンプレ（小文字）とは**別字形**。EVENT RESULT 専用テンプレが必要（§5.1）。

### 3.4 カード型ポップアップ（報酬獲得/アイテム獲得/RANK UP 等）

- 見た目: 中央のカード。上部にシアン→緑のヘッダ帯、右上に×。背景は暗転。
- **これらは×でなく背景（暗転部）のどこをタップしても閉じる**（実機確認）。
- アクション: `cardx`（状態判定は `detect_card_x` のヘッダ帯色検出で行う）→ 閉じるのは
  ×自体（クリックしても閉じない）でも色検出位置（背景汚染で不安定）でもなく、**カード外の
  背景をタップ**して閉じる。タップ位置は **右上の暗い背景 `P_CARD_DISMISS=(0.86, 0.16)`**。
  ※左下背景はカーソルが Dock/ホットコーナー付近へワープして危険なため右上を使う。
  閉じられず留まれば watchdog（`STUCK_STOP_SEC`=25s）で安全停止。

### 3.5 ライフが足りません（LIFE不足ダイアログ）

- 見た目: 「ライフが足りません。 LIFE♥N」、**きなこパン**行（LIFE 20回復・所持数・数量・回復ボタン）、
  その下に**ステラストーン**行（LIFE全回復）。右に大きな×、下に TAP SCREEN。
- アクション: `lifeshort` → **きなこパンの「回復」のみ**を押す（アンカー: マッチ位置＋(128,62)px
  ≈ ダイアログ上のきなこパン回復ボタン中央）。確認「N回復しました」の×を中央オフセットで閉じる。
- **製品要件: ステラは絶対に使わない**（座標を持たせていない）。きなこパン枯渇＝LIFE不足が
  連続 `MAX_LIFE_RECOVERS`(6) 回 → ステラへ移らず**停止**。
- LIFE収支: **EASY 消費 LIFE 15**、きなこパン +20。EASY周回ならきなこパン1個で十分回復。

### 3.6 連続ライブ再プレイ確認

- アクション: `replay` → アンカーで「はい」（マッチ位置＋`ANCH_REPLAY_YES`）。同曲・同難易度で再開。

### 3.7 楽曲選択 / フレンド選択 / 編成（連戦終了時のナビ）

- 楽曲選択: NEXTボタン検出。**NEXTの前に必ず EASY タブをタップ**（§4）。**曲は変更しない**
  （曲リストはタップせず現在選択中の曲のまま進める＝ユーザー要件）。
  ※一部の楽曲は選択画面が暗く(mean≈61)明るさゲート(65)を下回るため、暗め域(>50)では
  songselect テンプレを確認して gameplay 誤判定から救済する（§2 #2 参照）。
- フレンド選択: 「アピールスキル」固定ラベル（行内）をタップして選択（フレンドのスキル文は可変なため）。
- 編成: STARTボタンのマッチ位置を直接タップ。

### 3.8 PAUSE

- 見た目: 「PAUSE」見出し。
- アクション: `pause_resume.png` は**見出し**にマッチしボタンではない。マッチ位置でなく
  **固定の再開位置**（アンカー `ANCH_RESUME`）を押す。

---

## 4. 難易度 EASY 固定（製品要件）

**周回は必ず EASY で行う**（ユーザー要件。ノーマル等で周回しない）。

- 楽曲選択画面の難易度タブは左から **EASY / NORMAL / HARD / EXPERT**（LIFE 15 / 30 / 45 / 60）。
- **EASYタブ＝緑・最左「EASY✦ LIFE 15」、ウィンドウ相対 `P_EASY_TAB=(0.644, 0.718)`**（実測）。
- `songselect` ハンドラで **NEXT を押す前に EASY タブをタップ**して固定する。
- 連続ライブ再プレイは同難易度を維持するため、**楽曲選択に戻るたび EASY を選び直せば全周回が
  EASY に保たれる**。
- 確認: EVENT RESULT の難易度欄に緑「**EASY✦**」が出ること、ライブ中のCOMBOが低密度
  （37秒でCOMBO 12程度）であることで判別できる。

---

## 5. 今回の調査で判明した不具合と対処

イベント装飾（画面全体に走る「**KEEP OUT**」テープ）が既存テンプレのスコアを下げ／別要素を
誤検出させて停止する事例が複数発生。いずれも**テンプレ変種＋判定順**で解決した。

### 5.1 EVENT RESULT で停止

- 症状: 申請する押下後、ボタンが消えた EVENT RESULT がどのテンプレにも一致せず未知(menu)扱い
  → 26秒で安全停止。
- 原因: per-song「Result」(小文字青)テンプレしかなく、イベント「-EVENT RESULT-」(緑大文字)が未対応。
- 対処: `assets/templates/eventresult_title.png` を追加（ヘッダを切り出し）、専用状態 `eventresult`
  (閾値0.85, 中央タップで送る)。テープが他画面の同高さに出て斜体太字が構造相関(≈0.67)するため
  閾値を高めに。実機で216回処理し停止なしを確認。

### 5.2 編成画面が cardx 誤検出

- 症状: 連戦終了→編成復帰時、編成中央(y≈50%)のシアン緑帯を `detect_card_x` がカードヘッダと
  誤認→×連打で閉じられず停止。
- 対処: **STARTテンプレが明確(≈0.97)なら編成と確定**し、色ヒューリスティック(cardx)より先に判定
  （modal popup なら START が隠れスコアが落ちるため安全）。

### 5.3 LIFE不足ダイアログ未検出

- 症状: 「ライフが足りません。」が 0.81 で閾値0.85に届かず、代わりに cardx が暴走→停止。
- 対処: 当該ダイアログから `assets/templates/life_short_event.png` 変種を追加→1.00検出に回復。
  きなこパン回復はアンカー方式（マッチ中心＋固定px）のためマッチ中心が同じなら座標は不変。

> 教訓: イベント切替や停止発生時はまず `/tmp/i7dbg/*.png`（停止時スクショ）を見る。未知/誤検出なら
> 停止画面から該当テキストを切り出し `<stem>_*.png` 変種を追加（`load_templates` が自動取り込み）。
> 閾値はテープの構造相関を避けるため高めにし、新テンプレで実クリック点を必ず可視化検証する。

---

## 6. 停止条件と異常系

| 事象                    | 検出                                       | autolive の挙動 |
| ----------------------- | ------------------------------------------ | ---------------- |
| 未知の明るい画面        | menu に該当・`STUCK_STOP_SEC`(25s)超        | スクショ保存して安全停止（テンプレ未対応の合図） |
| ポップアップ閉じられない | cardx/closex/rankup が同画面に滞留          | 同上 watchdog で停止 |
| Result送りが進まない    | result/eventresult 連続 `RESULT_STUCK_SEC`(30s)超 | スクショ保存して停止（iOSシステムダイアログ等のオーバーレイ。§6.2） |
| gameplay 継続しすぎ     | `GAMEPLAY_TIMEOUT_SEC`(240s)超              | スクショ保存して停止（ミラーリング切断の暗オーバーレイ誤認防止） |
| きなこパン枯渇          | LIFE不足が連続 `MAX_LIFE_RECOVERS`(6)回     | ステラへ移らず停止 |
| ESC キー                | `esc_pressed()` を2回連続検出               | 手動キルスイッチで停止 |

### 6.1 ミラーリング切断（実機で頻発を確認）

- 症状: **ウィンドウが横(671×348)→縦(318×701)に変わり、画面が真っ黒(mean≈0)**。
  iPhone を物理的に触る／自動ロック／省電力で発生。autolive は §6 の gameplay timeout で安全停止。
- 復旧: `open -b com.apple.ScreenContinuity`（自動再接続）。ただし**ロック解除/認証が必要なことが多く、
  手動再接続が要る**（本調査では自動トリガーのみでは復旧しなかった）。復帰後の画面が楽曲選択なら
  そこから自動で周回再開できる。
- 予防: iPhone の自動ロックを「なし」に／充電しながら実行／実行中は iPhone に触れない
  （実カーソルがワープし続けるため Mac のマウスも操作しない）。

### 6.2 iOS システムダイアログの割込み（実機で発生）

- 症状: ライブ/Result 中に **iOS のシステムダイアログ**（例:「iMessage と FaceTime をオンに
  しますか？」使用しない/オンにする）が割り込む。背後の Result が `result:0.76` で残るため
  autolive は `result` と誤判定し中央タップを繰り返すが、システムダイアログはそれでは閉じず
  進まない（ライブ中に出るとノーツ入力も妨げられ MISS 多発）。
- 対処: `RESULT_STUCK_SEC`(30s) の watchdog で `result_stuck_*.png` を保存して停止。**復旧は
  手動**で安全な選択肢（iMessage/FaceTime は「使用しない」）をタップしてから再開する。
  システムダイアログはボタン配置が不定で誤タップが危険なため、自動タップはしない方針。

---

## 7. 関連ファイル

- `tools/autolive.py` — FSM 本体（`detect()` の判定順・各状態ハンドラ・定数）
- `assets/templates/*.png` — 判定テンプレ（`<stem>_*.png` 変種を自動併用）
- [`device-findings.md`](device-findings.md) — PAUSE 対策の詳細
- [`README.md`](README.md) — ドキュメント索引
- 停止時スクショ: `/tmp/i7dbg/`（`stuck_*`, `*_stuck_*`, `gameplay_timeout_*`, `life_depleted_*`）

---

## 付録A. 設計時の FSM 概念仕様（旧 specification.md §6 より移設）

> 実装前の設計時に汎用リズムゲーム周回フローとして記述した概念 FSM。実機で確認した具体仕様は
> 本書 §1〜§6 を正とし、本付録は設計意図の記録として残す。各状態に必要なテンプレ画像は
> [`architecture.md`](architecture.md) の「17.1 必要テンプレート画像チェックリスト」に対応。

### A.1 状態一覧

| #   | 状態                | 概要 |
| --- | ------------------- | ---- |
| S0  | `INIT`              | 初期化・キャリブレーション |
| S1  | `HOME`              | ホーム画面 |
| S2  | `EVENT_PAGE`        | 累計イベントページ |
| S3  | `LIVE_SELECT`       | ライブ（クエスト）選択 |
| S4  | `SONG_SELECT`       | 楽曲選択（任意） |
| S5  | `FORMATION_CONFIRM` | 編成確認 |
| S6  | `STAMINA_CHECK`     | スタミナ消費確認 |
| S7  | `STAMINA_RECOVER`   | スタミナ回復 |
| S8  | `LIVE_START`        | ライブ開始・AUTO 有効化 |
| S9  | `LIVE_PLAYING`      | AUTO 進行待ち |
| S10 | `RESULT`            | リザルト画面 |
| S11 | `REWARD_COLLECT`    | 報酬受け取り |
| S12 | `POPUP_HANDLE`      | 汎用ポップアップ処理（割込み） |
| S13 | `LOOP_DECISION`     | ループ判定・停止条件 |
| S14 | `RECOVERY`          | 不明画面からの復帰 |
| S15 | `SAFE_STOP`         | 安全停止（正常終了） |
| S16 | `ERROR_STOP`        | 異常停止 |

### A.2 状態遷移図（概念）

```text
INIT → HOME → EVENT_PAGE → LIVE_SELECT → (SONG_SELECT) → FORMATION_CONFIRM
                                                                  │
                                                                  ▼
   ┌────────────────────────────────────────────────  STAMINA_CHECK
   │                                                       │      │
   │                                           (不足)      │      │ (充足)
   │                                       STAMINA_RECOVER ┘      ▼
   │                                           │             LIVE_START
   │                                  (在庫なし→停止)              │
   │                                                               ▼
   │                                                         LIVE_PLAYING
   │                                                               │ (result検出)
   │                                                               ▼
   │                                     REWARD_COLLECT ←──── RESULT
   │                                           │
   │                                           ▼
   └──< (もう一度/ホーム) ──────────────  LOOP_DECISION ──→ SAFE_STOP
                                              ▲
   POPUP_HANDLE ◄─(任意状態から割込み)         │
   RECOVERY     ◄─(タイムアウト/不明画面)──────┘
   ERROR_STOP   ◄─(復帰失敗/連続エラー)
```

### A.3 各状態の定義

凡例: **判定**（その状態と認識するテンプレ）／**アクション**／**成功遷移**／**失敗・タイムアウト遷移**。
★ = ユーザーが実機からキャプチャして用意すべきテンプレ画像。

| 状態 | 判定（★テンプレ） | アクション | 成功遷移 | 失敗/TO遷移 |
| ---- | ----------------- | ---------- | -------- | ----------- |
| S0 INIT | （なし／起動時） | 設定読込・ウィンドウ検出・権限チェック・座標キャリブレーション・テンプレロード・カウンタ初期化 | 現画面判定→該当状態（通常 S1） | 権限/ウィンドウ不備→S16 |
| S1 HOME | ★`home_marker` | イベントバナー/メニューをタップ | S2 | S12走査→なければS14 |
| S2 EVENT_PAGE | ★`event_page_marker` | （任意）累計pt OCR記録、ライブ挑戦をタップ | S3 | S12 / S14 |
| S3 LIVE_SELECT | ★`live_select_marker` | 設定の難易度/ライブを選択 | S4 または S5 | S12 / S14 |
| S4 SONG_SELECT | ★`song_select_marker` | 設定楽曲（または先頭/固定）を選択 | S5 | S12 / S14 |
| S5 FORMATION_CONFIRM | ★`formation_marker` | 編成変更せず「次へ/決定」 | S6 | S12 / S14 |
| S6 STAMINA_CHECK | ★`stamina_confirm_marker` ＋ ★`stamina_shortage_marker` | スタミナOCR（任意）、不足無し→「開始/OK」 | 充足→S8 | 不足かつ回復ON→S7／不足かつ回復OFF/枯渇→S13／その他→S12/S14 |
| S7 STAMINA_RECOVER | ★`recover_dialog_marker` / ★`drink_*` / ★`item_empty_marker` | 指定アイテム選択→使用→確定、在庫トラッキング | S6（再確認、上限まで） | 在庫なし→S13／S12/S14 |
| S8 LIVE_START | ★`live_start_marker` ／ ★`auto_button_off`,`auto_button_on` | 必要なら AUTO を ON、開始タップ | S9 | S12 / S14 |
| S9 LIVE_PLAYING | ★`playing_marker`（終了は★`result_marker`出現で判定） | 長めポーリング待機、AUTO が OFF に戻っていないか監視、途中ポップアップ監視 | result検出→S10 | 楽曲尺+余裕超過→S14／プレイ中ポップ→S12 |
| S10 RESULT | ★`result_marker` | 「次へ/タップで進む」を連続タップ | S11 | S12 / S14 |
| S11 REWARD_COLLECT | ★`reward_marker` | 「OK/受け取る/閉じる」を順次タップ、派生ポップ連鎖処理 | 周回+1→S13 | S12 / S14 |
| S12 POPUP_HANDLE | ★`popup_*`（levelup/login_bonus/notice/network_error/generic_ok/generic_close） | 種別に応じ閉じる/OK/リトライ | 割込み元へ復帰（状態スタック）or 再判定 | 閉じない/未知→S14 |
| S13 LOOP_DECISION | （ロジック状態） | 停止条件を順に評価（[`architecture.md`](architecture.md) §5.4） | 継続→S1 または「もう一度」で S5/S6 へ（★`play_again_marker`） | 該当→S15/S16 |
| S14 RECOVERY | （いずれにも不一致） | リトライ+1、★`back_button`/`home_button`試行、（任意）スクショ保存、待って再判定 | 既知状態へ復帰 | リトライ上限超過→S16 |
| S15 SAFE_STOP | — | 停止理由・サマリをログ、リソース解放、exit 0 | 終了 | — |
| S16 ERROR_STOP | — | エラー・最終状態・最終スクショをログ、解放、exit≠0 | 終了 | — |

### A.4 横断的ルール（全状態共通）

1. **ポップアップ優先走査**: 待機ループの各サイクルで「期待テンプレ → ポップアップ群 → タイムアウト判定」の順。
2. **キルスイッチ**: 設定ホットキー押下で、現操作完了後ただちに S15 へ。
3. **タイムアウト**: 各待機状態は `timeouts.<state>`（無指定は `timeouts.default`）で打切り → S12走査 → S14。
4. **状態スタック**: S12 割込み時は復帰先のため直前状態を保持。
5. **デバウンス**: クリック後は `action_delay` の最小待機を入れ、連打/誤検出を防止。
