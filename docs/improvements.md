# 改善計画（docs/improvements.md）

## この文書について

- **作成日**: 2026-07-31 / 対象コミット: `913ebd6`（main）＋未コミットの実機資産（`tests/corpus_raw/`, `tools/ops/run_until.sh` ほか）
- **対象**: `tools/autolive.py` / `tools/note_engine.py` / `tools/driver.py` / `tools/ops/*` / `tools/probes/*` / `tests/*` / `docs/*` / `assets/prompts/*` の全体
- **作り方**: 複数の観点（safety / correctness / robustness / accuracy / maintainability / docs）から独立にレビューを行い、上がってきた指摘を1件ずつ**懐疑的に再検証**した。再検証では、実コードの grep・実機コーパス（`tests/corpus_raw/` 507枚）への `detect()` 実行・`/tmp/i7_autorun.log` と `/tmp/i7_supervisor.log` の実測集計・数値シミュレーションを用いた。
- **件数**: 提出された指摘 **90件** のうち、**11件は検証で棄却**（機構が成立しない／別の要因だった／提案が逆効果）。残る **79件** を本書に収録する。内訳は **confirmed 16件 / partial 63件**。
  - `partial` は「機構は実在するが、報告された影響が誇張されている」もの。本書では**どこまでが正しいか**を各項目に明記した。
  - 棄却した代表例: 「`P_EASY_TAB (0.644,0.718)` がステラ回復の9px下」（実測でステラは60px以上離れており、そもそも LIFE 不足画面は輝度172で暗所分岐に入らない）、「`--no-esc` でキルスイッチが失われる」（ESC を有効化しても supervisor が8秒後に再起動するため停止手段にならない）、「`NOTE_ROI_RADIUS` の幅相対が iPhone16 で遅発火」（シミュレーションで符号が逆）、「ベースライン EMA が波紋で押し上がる」（`fired` ガードで波紋本体は取り込まれない）など。
- **深刻度の基準**（このプロジェクト固有）:

| 深刻度 | 意味 |
|---|---|
| **Critical** | 課金アイテム（ステラ）の消費、または同等の不可逆な損失が**現に発生している** |
| **High** | 無人運用が長時間（数十分〜数時間）停止・空転する、または LIFE／きなこパンを継続的に浪費する |
| **Medium** | 周回精度・スループットの明確な劣化、安全装置の網羅漏れ、実機でしか気づけない不具合の温床 |
| **Low** | 実行時の誤動作を伴わない（保守性・テスト・ドキュメント・限定条件下の軽微な劣化） |

---

## 要約

### 深刻度別件数

| 深刻度 | 件数 | confirmed | partial |
|---|---:|---:|---:|
| Critical | 1 | 1 | 0 |
| High | 4 | 1 | 3 |
| Medium | 16 | 8 | 8 |
| Low | 58 | 6 | 52 |
| **合計** | **79** | **16** | **63** |

※ 同一機構に対する重複指摘（supervisor の rc 無視×3、ウィンドウ矩形の再取得なし×3、`--engine track`＋`--auto-circles` クラッシュ×3、判定順テーブル欠落×2、座標定数×3 など）は本書で統合済み。統合前の生件数が79件、統合後の項目数は Critical 1 / High 4 / Medium 16 / Low は分類別テーブルで列挙。

### 最優先で着手すべき3件

| # | 内容 | 理由 |
|---|---|---|
| **1** | **`ANCH_KINAKO` がステラの「回復」を直撃している**（[C-1](#c-1-きなこパン枯渇時に-anch_kinako-がステラの回復ボタンを直撃する)） | 唯一の Critical。**すでに本番で発火している**（`tests/corpus_raw/lifeshort/` の同日3枚でステラ所持が 58→55→52 と3個ずつ減少）。多重防御3層すべてを素通りする |
| **2** | **安全停止が終了コードに現れず supervisor が8秒後に無条件再起動する**（[H-1](#h-1-安全停止が終了コードに現れず-supervisor-が無条件に再起動する)） | C-1 の被害を無限化する増幅器。`life_recovers` がプロセス毎リセットされるため `MAX_LIFE_RECOVERS=6` が実質無効になる。単独でも「26〜36秒周期で数時間空転」が実測されている |
| **3** | **per-song Result が `cardx` に誤判定され、以後の再起動が全部同じ画面で死ぬ**（[H-2](#h-2-per-song-result-が-cardx-と誤判定され再起動トラップになる)） | 一度嵌ると supervisor の再起動が**すべて同じ画面で27秒死**する回復不能トラップ。実測で12:08〜12:28 の13回連続空転を確認 |

1 と 2 はセットで直す必要がある（1 だけ直しても 2 が別の停止理由を無限リトライさせ、2 だけ直しても 1 のステラ消費は止まらない）。

---

## Critical

### C-1: きなこパン枯渇時に `ANCH_KINAKO` がステラの「回復」ボタンを直撃する

- **対象**: `tools/autolive.py:147`（`ANCH_KINAKO = (128.0, 62.0)`）、`tools/autolive.py:1187`（`self.click_anchor(res["lifeshort"][2], ANCH_KINAKO)`）
- **判定**: confirmed（レビュー結果を受け、**本セッションで独立に再検証して確定**）
- **関連資産**: `tests/corpus_raw/lifeshort/{105609,132647,172455}_enter.png`（529x334 の実機キャプチャ、`.gitignore` 対象なので要資産化）

#### 独立再検証の結果（2026-07-31）

「すでに発生している」という重大な主張なので、レビュアーとは別に検証した。

実機フレームに対し `detect()` と `ANCH_KINAKO` を実際に適用した:

```
105609_enter: 529x334 state=lifeshort score=0.999  match中心=(212,108) → 着弾点=(340,170)
132647_enter: 529x334 state=lifeshort score=0.999  match中心=(212,109) → 着弾点=(340,171)
172455_enter: 529x334 state=lifeshort score=1.000  match中心=(208,112) → 着弾点=(336,174)
```

着弾点にマーカーを重ねて描画したところ、**きなこパン行が存在せず、着弾点はステラストーン
「回復」ボタンの中央**だった。ダイアログには「ステラストーン：LIFE 全回復 / 所持 58 / 3」の
1行しか無い。

さらに3枚の所持数を時刻順に並べると:

| 時刻 | ステラ所持 | 消費数量欄 |
|---|---:|---:|
| 10:56 | **58** | 3 |
| 13:26 | **55** | 3 |
| 17:24 | **52** | 3 |

**表示された消費数「3」ちょうどずつ減っている。** 同日の周回中に少なくとも2回、ステラ回復が
実行されたことを示す。仮説ではなく既遂の事実である。

#### 何が問題か

`lifeshort` ハンドラは「ライフが足りません。」見出しテンプレのマッチ中心から `(+128, +62)px` の位置を押す。SE 実測で「その位置がきなこパン行の『回復』ボタン」であることを前提にしている。

しかし実機キャプチャで確認したところ、**きなこパンが 0 個のときダイアログはきなこパン行をグレーアウトせず、行ごと消して上に詰める**。その結果、旧きなこパン行の位置（window相対 y≈0.508）に**ステラストーン行がそのまま繰り上がる**。

3枚すべてで:

| フレーム | match中心 | 着弾点 `match + (128,62)` | ステラ「回復」ボタン矩形 | 判定 |
|---|---|---|---|---|
| 105609 | (212.5, 108.0) | **(340.5, 170.0)** | x=313..365, y=158..178 | 矩形の中央 |
| 132647 | (211.5, 109.0) | (339.5, 171.0) | 同上 | 矩形内 |
| 172455 | (208.5, 112.0) | (336.5, 174.0) | 同上 | 矩形内 |

`detect()` はいずれも `lifeshort` を score 0.999〜1.000 で返す（テンプレは見出しだけを見ており、行の中身を一切見ていない）。

#### 放置するとどうなるか

**すでに起きている。** 上記3枚のステラ所持数は 10:56=58 → 13:26=55 → 17:24=52 と、消費数量欄の「3」ちょうどずつ減っている。同一日の周回中に少なくとも2回、ステラ回復が実行された。

`docs/navigation.md` が謳う「ステラ不使用の保証（多重）」3層はすべて素通りする:

| 防御層 | なぜ効かないか |
|---|---|
| (i) ステラの座標をコードに持たない | アンカーが**偶然**ステラを指すので座標の有無は無関係 |
| (ii) `MAX_LIFE_RECOVERS=6` で停止 | ステラ回復は**成功して LIFE が全回復しライブに入る**ため、`tools/autolive.py:1192` の `self.life_recovers = 0` でリセットされ永久に発火しない |
| (iii) 未知ダイアログは `STUCK_STOP_SEC` で停止 | 見出しは正しくマッチするので `lifeshort` と確定し、未知画面にならない |

しかもログには「LIFE不足 → きなこパンで回復（1回目, **ステラ不使用**）」と表示されるため、ログを読んでも気づけない。無人運用中は LIFE が尽きるたびに 3個ずつ溶け続ける。

#### どう直すか

1. **クリック前に「押そうとしている行がきなこパン行である」ことを画像で確認する**（唯一有効な対策）。
   - `assets/templates/kinako_row.png`（きなこパン行のアイコンまたは「きなこパン」ラベル）を新規取得し、`lifeshort` 検出時にダイアログ内で照合。
   - マッチしたら**そのマッチ位置基準**で「回復」ボタンを押す（`ANCH_KINAKO` を「見出し基準」から「きなこパン行基準」に変える）。
   - マッチしなければ**クリックせず**、`/tmp/i7dbg/life_kinako_missing_*.png` を保存して安全停止する。
2. **枯渇 sentinel を導入**: きなこパン行が見つからずに停止したら `/tmp/i7_kinako_depleted` を置き、autolive 起動時にこれがあれば `lifeshort` ハンドラを無効化して即停止する（H-1 の再起動抑止とセット）。
3. **回帰テストを固定**（M-13 と同一作業）: `tests/corpus_raw/lifeshort/105609_enter.png` を `tests/frames/lifeshort_depleted_529x334.png` としてコミットし、
   - `detect()` が `lifeshort` を返すこと
   - **`ANCH_KINAKO` を適用した着弾点がステラ「回復」ボタン矩形に入らないこと**（失敗時のメッセージに「ステラ側へ落ちる」と明示）
   を検証する。書き方の前例は `tests/test_detect_dialogs.py:58-71`（`ANCH_RESUME_YES` の着弾点テスト）。

#### 検証の所見

- レビュー時点の当初仮説は「レイアウトが変わるかもしれない（未検証）」だったが、リポジトリ内の実キャプチャで**現に変わっていること**、および**着弾点がステラボタン中央に入ること**を確認したため critical に引き上げた。
- レビュアーが併せて提案した「着弾点 y がマッチ中心から +90px を超えたらクリックしない」というサニティ上限は**効かない**（枯渇時も着弾は同じ +62px）。採用しないこと。
- 「`ANCH_KINAKO` の余裕が1行分しかない設計」という言い方は本質ではない。本質は「行が消えて詰まる」ことなので、対策は行の内容確認に限る。

---

## High

### H-1: 安全停止が終了コードに現れず、supervisor が無条件に再起動する

- **対象**: `tools/autolive.py:1185, 1217, 1264, 1280, 1300, 1386, 1402`（全ての安全停止 `break`）、`tools/ops/supervise_autolive.sh:34-45`
- **判定**: partial（機構は confirmed。影響の一部が誇張）
- **統合**: 同一機構への3件（safety / correctness / robustness 観点）を統合

#### 何が問題か

安全停止はすべて `_loop()` 内の `break` で、その後 `run()` が正常復帰し `main()` が return するだけ = **終了コード 0**。`sys.exit` はファイル全体に1つも無い。

一方 supervisor は:

```sh
python -u tools/autolive.py ... ; rc=$?
log "autolive exited rc=$rc"      # ← ログに出すだけ
...
log "restarting in 8s..."; sleep 8
```

`rc` を条件に使う分岐は存在せず、break するのは「TARGET 時刻到達」の2箇所だけ。つまり**停止理由に関係なく8秒後に再起動**する。

さらに `self.life_recovers` は `__init__`（`tools/autolive.py:437`）で 0 に戻るため、`MAX_LIFE_RECOVERS=6` は「プロセスあたり6回」でしかない。

#### 放置するとどうなるか

実測済み（`/tmp/i7_supervisor.log` / `/tmp/i7_autorun.log`）:

- 「カードポップアップを閉じられず停滞」で rc=0 終了 → 8秒後に再起動 → 同じ画面で27秒後にまた停止、を **attempt #34〜#45 の12連続**（約36秒周期）。ログ全体で `完了: 0 回クリア` が **71件**。
- `tools/ops/run_until.sh` の冒頭コメントも同現象を記録: 「切断中は毎回『未知画面に25s停滞→安全停止』で終わるため、26秒ごとの無駄な再起動を延々と繰り返してしまう（実測 2026-08-01: attempt #7 まで空回り）」。
- **C-1 と組み合わさると致命的**: きなこパン枯渇→ステラ誤押下→ライブ突入→`life_recovers=0` リセット、というループが止まらない。仮に C-1 を直して「枯渇で停止」するようにしても、8秒後に再起動して同じ6回を繰り返す。

ログ上は `autolive exited rc=0` が並ぶだけなので、正常な時間切れ・クラッシュ再起動・復旧不能な安全停止を運用者が区別できない。

#### どう直すか

1. **終了コードを分離する**（`tools/autolive.py`）:
   ```python
   EXIT_OK = 0            # 正常終了（loops 到達 / max-seconds 到達 / ESC）
   EXIT_SAFE_STOP = 42    # 安全停止（人間の確認が必要）
   EXIT_ERROR = 1         # 例外
   ```
   - `_loop()` の各 `break` の直前で `self.stop_reason = "kinako_depleted" | "gameplay_timeout" | "cardx_stuck" | ...` を設定。
   - `run()` が `stop_reason` を返し、`main()` が `sys.exit(EXIT_SAFE_STOP if reason else EXIT_OK)`。
2. **supervisor 側で再起動を止める**（`tools/ops/supervise_autolive.sh`、`rc=$?` の直後）:
   ```sh
   if (( rc == 42 )); then
     log "safety stop (rc=$rc); NOT restarting"
     touch /tmp/i7_safe_stop_fired
     break
   fi
   ```
3. **サーキットブレーカ**: 「直近 N 分に M 回以上 autolive が終了した」または「クリア数が増えないまま4回終了した」で supervisor 自体を停止する。判定手法は `tools/ops/freeze_sentinel.sh:20-22` の `grep -c "ライブ クリア"` 差分がそのまま流用できる。
4. **バックオフ**: `sleep 8` を 8→16→32→…（上限300秒）にし、クリアが1回でも進んだらリセットする。

#### 検証の所見（partial の範囲）

- **成立する**: 安全停止が rc=0 であること、supervisor が rc を見ないこと、`life_recovers` がプロセス毎にリセットされること、実測で長時間空転していること。
- **誇張**: 「未知の明るいダイアログで25秒間 clickX を試みる」は**誤り**。`menu` 分岐（`tools/autolive.py:1389-1403`）は設計どおり**一切クリックせず** `time.sleep(0.3)` で待つだけ。再起動しても未知画面に合成クリックは1回も飛ばない。
- **誇張**: 「難易度が EASY 以外になり1プロセスあたりきなこパン6個消費」は再現しない（`life_recovers` はライブ突入のたびリセットされるので、break には「ライブに一度も入れないまま連続7回 lifeshort」が必要）。
- **部分的な緩和が存在**: `tools/ops/freeze_sentinel.sh:39-40` の「launch attempt が4増えたのにクリアが増えない」判定がこの再起動ループを検知しうる。ただし `MAX_RECOVERIES=6` 超過時は `exit 1` するだけで `pkill -f supervise_autolive.sh`（48行）に到達せず、supervisor は8秒周期を続ける。しかも `run_until.sh` は sentinel を起動しない。

---

### H-2: per-song Result が `cardx` と誤判定され、再起動トラップになる

- **対象**: `tools/autolive.py:310-330`（`detect_card_x`）、`tools/autolive.py:1095-1099`（`cardx` を `result` より先に評価）、`tools/autolive.py:1250-1267`（`cardx` ハンドラ）
- **判定**: partial（機構と実害は confirmed。「毎回必ず」は誤り）

#### 何が問題か

`detect_card_x` はテンプレを使わず色条件だけで判定する:

```python
band = (G > 180) & (R < G - 20) & (B > 120)
rows = np.where(rowsum > 0.18 * w)[0]      # ← 行内の「合計」であって連続帯ではない
```

per-song Result 画面には LV表示の**緑色 EXPカードが横一列に5枚**並ぶ。この5枚の緑の上辺が同じ行に来ると、行方向に合算されて1本の帯に見え、条件を満たす。

実測（`/tmp/i7dbg/cardx_stuck_27.png` = per-song Result）:
- 閾値を超えるのは 151〜153行のみ、`rowsum = 201` 対 閾値 `0.18*w = 120.8`
- `detect_card_x` → (515,157) を返し、`detect()` は `cardx` を返す
- 同フレームの `result` スコアは 0.851（閾値 0.55）なので、cardx を外せば正しく `result` になる

`cardx` ハンドラは検出した×位置ではなく固定の `P_CARD_DISMISS = (0.86, 0.16)` を叩くため、Result は送られない。

#### 放置するとどうなるか

25秒で `cardx_stuck_*.png` を保存して停止するが、**ゲームは Result 画面に留まったまま**なので、supervisor が8秒後に再起動しても初回フレームで同じ判定になり、約27秒でまた停止する。

実測: 12:08〜12:28 に **13回連続で attempt が空転**（`clear 0/99999` のまま）。人が手で画面を送った 12:28 以降にようやく周回が再開し、その後は31クリアした。**無人運用中に一度嵌ると、以後の残り時間がすべて空転する。**

#### どう直すか

1. **`detect_card_x` の帯判定を「1本の連続した帯」に限定する**（本命）:
   ```python
   # 現状: rowsum = band[y].sum() の総和で判定
   # 変更: 行内の band の最長連続ラン長 >= 0.18 * w を要求
   ```
   EXPカード5枚のような**離散した緑ブロックの合算**を排除できる。
2. **`cardx` ハンドラにフォールバックを入れる**: 同じ画面で N 回（例3回）閉じられなかったら `cardx` を一時的に抑制（既存の `suppress_cardx_until` 機構が流用できる）して他状態で再判定する。
3. **回帰テストを固定**: `/tmp/i7dbg/cardx_stuck_27.png` を `tests/frames/result_expcards_671x348.png` としてコミットし、`detect()` が `result` を返すことをテストする。

#### 検証の所見（partial の範囲）

- **成立する**: 色判定が緩いこと、`cardx` が `result` より先に評価されること、実フレームで再現すること、再起動トラップになること（実ログで13回連続空転）。
- **誤り**: 「1ライブをクリアしても Result を抜けられず**必ず**停止する＝周回が1周も回らない」は誤り。同じログの attempt #45 は 31 クリアしている。EXPカードの描画アニメ途中では `rowsum` が閾値に届かないため、発火はタイミング依存。
- **誤り**: 「15時間無人運用しても成果ゼロ」は不正確。34件の「閉じられず停滞」のうち33件は `clear 0/99999`（Result が完全描画された状態でのコールドスタート）で、ライブ中に嵌ったのは1件のみ。
- **注意**: 単純に `result` を `cardx` より前に出す案は、`tools/autolive.py:1091-1092` のコメント（「Result の上に重なって出るため」）と `result` の緩い閾値 0.55 のため、Result に重なった報酬ポップアップまで `result` 判定→中央タップになり退行しうる。**採用しないこと。**

---

### H-3: `run_until.sh` の切断ガードは起動時の1回しか評価されない

- **対象**: `tools/ops/run_until.sh:42-59`（特に51行）、`tools/ops/supervise_autolive.sh:24-46`
- **判定**: confirmed

#### 何が問題か

```sh
if connected; then
  log "supervisor 起動（残り ${remain}s）"
  tools/ops/supervise_autolive.sh "$TARGET"   # ← & が無い＝フォアグラウンド
  log "supervisor 終了"
```

`supervise_autolive.sh` の while ループは break が2箇所しかなく、どちらも「TARGET 時刻到達」。つまり**一度起動すると目標時刻まで return しない**。`connected()` は起動直後の1回しか実行されず、その後どれだけ切断しても `sleep 30` の待機ロジックに入らない。`sleep 30` は「未接続」側の分岐（58行）にしかない。

#### 放置するとどうなるか

このスクリプトを追加した目的（コミット `a8c6711`「切断中の空回り再起動を止める」）が達成されない。実測:

- `/tmp/i7_runner.log` は2行のみ（`08:08:22 runner start` / `08:08:24 supervisor 起動（残り 54000s）`）で「supervisor 終了」が無い
- 同時刻の `/tmp/i7_supervisor.log` では attempt #1（08:08:24）から #46（13:36）まで動き続けており、**runner は5時間半制御を取り戻していない**

結果、防ぎたかった空回り再起動（H-1 と同じ症状）がそのまま発生する。

#### どう直すか

**選択肢B（推奨・階層を減らす）**: 切断判定を `supervise_autolive.sh` の再起動ループ内（`sleep 8` の直前）に移す。

```sh
# supervise_autolive.sh の再起動判定の直前
if ! connected; then
  log "ミラーリング切断中。60s 待機して再確認する"
  sleep 60
  continue
fi
```

`run_until.sh` は不要になるか、単なる薄いラッパーになる。ラッパーが2階層あることが H-4 の二重起動の原因でもあるため、こちらが構造的に安全。

**選択肢A**: `run_until.sh` 側で supervisor を `&` 起動して PID 保持 → 30秒ごとに `connected()` を評価 → 切断なら `kill` → 復帰したら再起動。ただし H-4 の相互作用が残る。

#### 検証の所見

- 構造・実測ログとも指摘どおり。
- ただし影響の帰属に誤りがある: 12:08〜12:28 の35秒周期の空回りの原因は**切断ではなく H-2 の cardx 停滞**であり、この修正だけでは止まらない。「gameplay が 240s 継続（切断の可能性）」26件も7/31からの累積で、この runner セッション内の回数ではない。
- 被害はログ/CPU の空回りに限られる（切断中は `find_window` 例外で即死するか未知画面で安全停止するため、危険なタップは発生しない）。

---

### H-4: `freeze_sentinel.sh` / `pause_guard.sh` の kill を `run_until.sh` が即座に打ち消す

- **対象**: `tools/ops/freeze_sentinel.sh:48-51`、`tools/ops/pause_guard.sh:28-34`、`tools/ops/run_until.sh:42-59`
- **判定**: partial（機構は confirmed。両方を同時起動した場合に限る）

#### 何が問題か

`freeze_sentinel.sh` と `pause_guard.sh` はどちらも:

```sh
pkill -f supervise_autolive.sh
pkill -f "autolive.py"
```

で周回を止めるが、この pkill パターンは `run_until.sh` 自身（argv は `/bin/zsh tools/ops/run_until.sh <target>`）に一致しない。フォアグラウンドの supervisor が消えると `run_until.sh` は「supervisor 終了」をログしてループ先頭に戻り、`connected()` が true なら**即座にもう1つ supervisor を起動する**。

これにより2つの障害が起きる:

1. **復旧処理との衝突**: `freeze_sentinel` が `recover_freeze.py`（⌘1→⌘2→カード上スワイプでアプリ強制終了→Spotlight 再起動→最大300秒のナビ）を実行している最中に、新しい autolive が同じウィンドウへ打鍵を送る。`recover_freeze.py` の docstring「前提: supervisor / autolive は停止済みであること」が破られる。さらに `recover_freeze.py:86-88` は「復旧中に勝手にライブを始めない」ため prev_result/replay を必ず「いいえ」で抜ける設計なのに、並走 autolive は resumelive/replay をいずれも「はい」で押す。
2. **supervisor の二重化**: 復旧成功後に `freeze_sentinel.sh:51` が自前で `nohup supervise_autolive.sh &` を起動するため、`run_until` 側と合わせて **supervisor 2組・autolive 2プロセス**が TARGET まで並走する。
3. **pause_guard の完全無効化**: guard は farm を kill して `/tmp/i7_pause_guard_fired` を置いて exit するが、`run_until.sh` はこのフラグを一切参照しない（grep で0件）。0〜30秒で周回が復活し、PAUSE 嵐による LIFE 浪費を止められない。

なお、supervisor/autolive のどちらにも多重起動防止（pidfile / flock / pgrep）は存在しない（`grep -rn "flock|pgrep|pidfile|lockfile" tools/ops/` は0件）。

#### 放置するとどうなるか

autolive が2プロセス同時に走ると、双方が `CGWarpMouseCursorPosition` で実カーソルを別々の座標へワープさせながら HID クリックを撃ち合う。打鍵が互いを潰して MISS が急増し、`MAX_LIFE_RECOVERS` がプロセス単位のためきなこパン消費が倍化する。ログも両者が混ざって復旧判定（launch attempt / クリア数）が信頼できなくなる。

実測: 2026-07-31 20:49:58〜21:15:53 に supervisor 2組が約26分並走した痕跡が `/tmp/i7_supervisor.log` に残っている。

#### どう直すか

1. **停止をフラグファイルで表現する**（構造的解決）:
   - `freeze_sentinel` / `pause_guard` は pkill せず `/tmp/i7_halt` を touch するだけにする。
   - `run_until.sh` と `supervise_autolive.sh` はループ先頭で `/tmp/i7_halt` を見て自発的に終了する。
   - 復旧中は `/tmp/i7_recovering` を置き、これがある間は supervisor を起動しない（復旧完了で削除）。
2. **`freeze_sentinel.sh:51` の自前 supervisor 再起動を廃止**し、再起動の責務を1箇所（run_until または supervisor）に集約する。
3. **応急処置**（1が入るまで）:
   - `run_until.sh` のループ先頭で `/tmp/i7_pause_guard_fired` と `/tmp/i7_freeze_unrecovered` を見て break する
   - supervisor 起動前に `pgrep -f supervise_autolive.sh` で既存プロセスが無いことを確認
   - 再起動前に `sleep 15` を入れる
4. **排他ロック**: macOS には `flock` が無いので `mkdir /tmp/i7_run.lock` の atomic mkdir を使う。

#### 検証の所見（partial の範囲）

- **成立する**: pkill が `run_until.sh` に一致しないこと、`run_until.sh` が待機なしで再起動すること、多重起動防止が存在しないこと、supervisor 2組の並走痕跡が実ログにあること。
- **範囲の限定**: この経路は `run_until.sh` と `freeze_sentinel.sh`（または `pause_guard.sh`）を**同時起動した場合にのみ**成立する。`docs/operations.md` の標準手順は `supervise_autolive.sh` 単体、`tools/ops/README.md` のスニペットは supervisor + freeze_sentinel で、run_until を含む手順書はリポジトリ内に存在しない（`run_until.sh` は最新コミットで追加されたばかりで運用文書に未反映 = L-D5）。
- **誇張**: 「PAUSE メニューの『諦める』を踏む確率が跳ね上がる」は推測。autolive は既知座標しか押さないので、増えるのは「片方の押下が他方の状態遷移とズレる」誤爆であって、特定ボタンの誤タップは実証されていない。
- **誇張**: ステラ誤使用・課金には至らない（lifeshort ハンドラの制約と未知画面ノークリック方針が両プロセスで効く）。

---

## Medium

### M-1: `detect_content_rect` の採用条件に暗さゲートが無く、明るい画面で content が汚染される

- **対象**: `tools/autolive.py:1152-1155`（採用条件）、`tools/autolive.py:333-353`（`detect_content_rect`）
- **判定**: confirmed

**問題**: コメントは「暗いゲーム画面でのみ正しく取れる」と書いているが、ガードは `if rect[1] - rect[0] < frame.shape[0] - 4:` だけで**明暗を一切見ていない**。

実測（SE 529x334、`tests/corpus_raw`）:

| 状態 | 検出 rect | 採用? | 正しい値 |
|---|---|---|---|
| gameplay / cardx / pause | (38, 325) | ✅ | (38, 325) |
| lifeshort / result / closex 等 | (0, 333) | ❌（閾値で弾かれる） | — |
| **formation / songselect / friendselect** | **(59〜60, 325)** | **✅ 採用されてしまう** | (38, 325) |

formation の 30..37行は macOS タイトルバー（輝度206〜211）、38行からゲーム自身の明るいヘッダ（96,97,98,95,124,175…）が続き、59行でようやく70を下回る。つまり **ゲーム内容を21行取りこぼした誤った値**がキャッシュされる。

**影響**: `game_center_px()` が (264.5, 181.5) → (264.5, 192.0) と **y が 10.5px 下へずれる**。`OFF_LIFE_CONFIRM` は `SE_GAME_CENTER = (264.5, 181.5)` を前提に導出された値（`(0.78*529, 0.41*334) - (264.5,181.5) = (148.1,-44.6)` と算術一致）なので、songselect→friendselect→formation を経由した直後に LIFE 不足ダイアログが出ると、「N回復しました」確認の × を 10.5px 外して閉じられない。×のヘッダ帯は高さ約20pxしかないため帯の外に落ちる。以降 closex/cardx の watchdog（25秒）で安全停止 → supervisor 再起動 → 同じ経路 → 再び失敗、というループになる。

`replay→はい` 経由で LIFE 不足になった場合は直前が gameplay（暗）なので content が正しく、**経路依存の間欠不具合**になる。

**直し方**:
```python
# tools/autolive.py:1152 付近
if float(frame.mean()) < DARK_THRESH and rect[1] - rect[0] < frame.shape[0] - 4:
    self.content = rect
```
加えて、得られた top が直前値から 10px 以上飛んだら捨てるか、複数フレームの中央値を採る。

**検証の所見**: 影響列挙のうち以下は成立しない — Result 中央送り（`OFF_RESULT_ADV`）は gameplay 直後なので content が正しく実害なし、`OFF_MENU_SAFE` は未使用（menu 分岐はクリックしない）。ステラ誤タップにも波及しない（外した着弾点はカード白地）。

---

### M-2: ウィンドウ矩形を起動時に1回しか取得しない

- **対象**: `tools/autolive.py:432`（`self.win = driver.find_window()`）、`tools/autolive.py:1151`（`driver.grab(self.win)`）
- **判定**: confirmed（3件の重複指摘を統合）

**問題**: `find_window()` は `__init__` の1回だけ。以降 `driver.grab(self.win)` も全クリック座標計算（`content_to_screen` 487-494、`click_window` 610-611、`game_center_px` 621-622）も初回の x/y/w/h を使い続ける。`driver.grab` は win_id ではなく**画面の絶対座標領域**を mss で読むだけなので、ウィンドウが消えても移動しても「その領域」を撮り続ける。`_keep_front`（994-1002）は最前面化するだけで bounds を読み直さない。

**実機証跡**:
- `/tmp/i7dbg/stuck_4093.png`（671x348）は**ゲーム画面ではなく macOS のデスクトップ壁紙**。`/tmp/i7_autorun.log:13430` に対応する「未知画面に 25s 停滞 → 安全停止」があり、直後の再起動は `RuntimeError: iPhone ミラーリングのウィンドウが見つかりません` で即死 = その時点でウィンドウは消えていた。
- `/tmp/i7dbg/stuck_37.png` は 671x348 で起動したのに中身が壁紙＋中央の縦長「iPhoneが使用されました」パネル。切断時のウィンドウは横 671x348 → 縦 318x701 に変わる（`docs/screen-transitions.md` §6.1 に記載）。

**影響**: 旧矩形の内容が明るければ `menu` 判定でクリックせず25秒で安全停止する（実測3例はすべてこれ）。**暗ければ** `bright < DARK_THRESH(65)` で `gameplay` と誤判定され、`_keepalive` が `KEEPALIVE_GAP_SEC=0.6` ごとに旧矩形内の CIRCLES 座標へ実カーソルワープ＋HIDクリックを送る（約1.7回/秒、最大 `GAMEPLAY_TIMEOUT_SEC=240` 秒で計約400回）。旧矩形に重なっている他アプリを叩きうる。

**直し方**:
```python
# _loop() 内、2〜5秒に1回
if now - self.last_win_check > 3.0:
    self.last_win_check = now
    try:
        w = driver.find_window()
    except RuntimeError:
        self.log("ミラーリングウィンドウが消失 → 安全停止"); break
    if (w["x"], w["y"], w["w"], w["h"]) != (self.win["x"], ...):
        self.win = w
        self.content = None          # content キャッシュ無効化
        self.circles_calibrated = False   # 円補正もやり直し
```
加えて `_click_screen`（497-515）の先頭で「クリック点が `self.win` の矩形内か」をアサートし、外なら送らずログに残す。`find_window()` は `CGWindowListCopyWindowInfo` の全ウィンドウ走査なので**毎フレームは不可**（37FPS の打鍵ループに乗せない）。

**検証の所見（partial 由来の限定）**: 「毎秒150回規模のクリック」「ブラウザの購入ボタンを押す」は成立しない。明るい画面では1回もクリックしない（menu 分岐）、暗くても発火するのは `_keepalive` だけで約1.7回/秒。既存の watchdog（25秒 / 240秒）が上限を掛ける。

---

### M-3: `freeze_sentinel.sh` の `grep -c ... || echo 0` が `"0\n0"` を生む

- **対象**: `tools/ops/freeze_sentinel.sh:20-22, 33, 39-40`
- **判定**: partial

**問題**: `grep -c` は0件のとき **stdout に "0" を出しつつ exit 1** を返すため、`$(grep -c ... || echo 0)` は `0\n0`（改行入り）になる。以降の `(( c > base_clear ))` / `(( w - base_warn >= 2 ))` は zsh の `bad math expression` で**常に偽**になる。zsh 実測で再現済み。

汚染条件は「ファイルが存在し、かつ該当0件」（ファイル欠損時は grep が何も出さず exit 2 なので clean な "0" になる）。つまり **/tmp をクリアした直後（Mac 再起動後）の最初の起動**が該当する。

**影響（指摘とは向きが違う）**:
- 条件A（`warn` 2回増でフリーズ検知）は死ぬが、条件B（`attempt` 4回増）は `base_att` が常に1以上で clean なため生きる。cardx 停滞は必ず autolive 終了 = attempt 増を伴うので、**約70秒遅れて条件Bが捕まえる**。
- より実害があるのは **33行のベース更新も壊れる**点。健全に周回していても `base_clear` がリセットされないため、切断や通常クラッシュによる supervisor 再起動が通算4回に達した時点で `restart_loop` が**誤発火**し、正常周回中の autolive とゲームアプリを強制終了する。誤発火は `MAX_RECOVERIES=6` を消費し、6回超過で sentinel 自身が exit して以後は本当のフリーズに無防備になる。

つまり症状は「発火しない」ではなく「**A が遅れ、B が過敏になる**」。

**直し方**:
```sh
base_warn=$(grep -c "閉じられず停滞" "$LOG" 2>/dev/null); base_warn=${base_warn:-0}
```
`grep -c` は0件でも "0" を出すので `|| echo 0` 自体が不要。3箇所すべて同様に直し、算術には `${w:-0}` の明示デフォルトを付ける。

---

### M-4: 停滞 watchdog が11状態に存在せず、進捗ベースの大域 watchdog も無い

- **対象**: `tools/autolive.py:1404-1410`（`menu_since` / `result_since` のリセット条件）
- **判定**: partial

**問題**: `if state not in ("menu", "rankup", "closex", "cardx"): self.menu_since = None` により、**pause / battery / friendreq / replay / dldialog / story / resumelive / liveassist / songselect / friendselect / formation の11状態には停滞検出が一切無い**。

特に `pause` は `gameplay_since` こそ保持されるが、タイムアウト判定自体が gameplay 分岐内（1208行）にしかないため、PAUSE に張り付くと永久に評価されない。`docs/navigation.md:227` の旧 `pause_resume` バグはまさにこの形（PAUSE検出→無効クリックの無限ループ）で発生し、人間が気づくまで止まらなかった。

`loops_done` が増えないことを検知する大域 watchdog も存在しない。

**影響**: 「テンプレはマッチし続けるが押しても遷移しない」状態に入ると、`--max-seconds` の残り時間ぶん（supervisor 経由なら目標時刻まで）同じ座標を叩き続け、ライブ0クリアで空回りする。プロセスが落ちないため `freeze_sentinel.sh` の「launch attempt が増える」判定でも検知できない。

**直し方**:
```python
# 状態別タイマーに一般化
self.state_since = {}   # state -> 最初にその state になった時刻
...
if state != self._prev_state:
    self.state_since = {state: now}
elif now - self.state_since[state] > STUCK_STOP_SEC_FOR[state]:
    save_screenshot(f"{state}_stuck"); break
```
加えて `PROGRESS_TIMEOUT_SEC = 600`（loops_done が10分増えなければ停止）という進捗ベースの大域 watchdog を入れる。こちらは状態フラップにも強い。

**検証の所見（partial の範囲）**: 「押している先が課金導線であっても止まらない」は成立しない。無保護な11状態はいずれもテンプレが閾値（0.74〜0.85）を超えて既知画面と確定した場合のみ入り、クリックは `click_match` / `click_anchor` でマッチ位置追従、唯一の盲目座標 `P_EASY_TAB` も songselect 確定後の EASY タブのみ。実害は「同じ既知画面を延々叩いて周回が進まない」= 可用性の問題。また `menu↔result` フラップで両タイマーがリセットされ続ける、というシナリオは実機コーパスで裏付けが取れなかった（非 result 画面の result スコア最大は 0.525 で閾値 0.55 に届かず、届く2枚は判定順で先に cardx に確定する）。

---

### M-5: ops スクリプトに排他制御が無い

- **対象**: `tools/ops/run_until.sh` / `supervise_autolive.sh` / `freeze_sentinel.sh` / `pause_guard.sh`（全体）
- **判定**: partial

**問題**: 4本のいずれにも flock・PIDファイル・pgrep による起動前チェックが無い（`grep -rn "flock|pgrep|pidfile|lockfile" tools/ops/` は0件）。加えて**ドキュメントが3つの異なる入口を推奨している**:

| 場所 | 推奨されている入口 |
|---|---|
| `docs/operations.md:5-7` | `nohup tools/ops/supervise_autolive.sh <target_epoch> &`（「現在の推奨構成」） |
| `tools/ops/README.md:8` | `run_until.sh`（「長時間の無人運用はこれを使う」） |
| `tools/ops/README.md:20-23` | supervisor + freeze_sentinel の2本起動 |
| `CLAUDE.md:64-65` | `supervise_autolive.sh` |

どれが排他かの記述が無いため、運用者が重ねて起動しやすい。

**影響**: H-4 と同じ（打鍵干渉による MISS 増、きなこパン消費の倍化、復旧判定の破綻）。

**直し方**: 各スクリプト冒頭に atomic mkdir によるロックを入れる（macOS には flock が無い）:
```sh
LOCK=/tmp/i7_run.lock
if ! mkdir "$LOCK" 2>/dev/null; then echo "already running"; exit 1; fi
trap 'rmdir "$LOCK"' EXIT
```
加えて `docs/operations.md` / `CLAUDE.md` / `tools/ops/README.md` の入口を1本に統一し、他は「単体デバッグ用」と明記する（L-D5 と同時に行う）。

**検証の所見**: `run_until.sh` 単体は supervisor を同期呼び出しするので自己二重化はしない。確定的に2組になるのは `run_until` + `freeze_sentinel` の併用時（H-4）。

---

### M-6: `--flick` の赤検色点が飛行線から外れ、外側2レーンで機能していない

- **対象**: `tools/autolive.py:687-705`（`_approach_red`）、`tools/autolive.py:208-213`（`FLICK_APPROACH_FRAC`）
- **判定**: partial

**問題**: 検色点を `円 + (ARC_CENTER - 円) * (1 - FLICK_APPROACH_FRAC)` に置いているが、ノーツは `ARC_CENTER=(0.49,0.50)` ではなく `note_engine.SPAWN=(0.50,0.06)` から飛んでくる。検色点は真の飛行直線から外れる。

正方形ROI（半幅 r、角まで r×1.414）で線分-箱交差を判定した結果:

| 円 | SE(r=18.5) 垂直距離 | 判定 | iPhone16(r=23.5) | 判定 |
|---|---:|---|---:|---|
| c0（左端） | 31.5px | **箱外** | 36.2px | **箱外** |
| c1 | 14.6px | 箱内 | 18.0px | 箱内 |
| c2 | 18.8px | 箱内（角で交差） | 23.2px | 箱内 |
| c3（右端） | 33.9px | **箱外** | 39.0px | **箱外** |

実測でも裏付けが取れた。実機78フレームで「動く明るい画素」率を比較すると、現行検色点 vs SPAWN線上の同距離点で lane0 3.07%→4.69%、lane1 3.47%→6.29%、lane2 2.23%→4.88%、lane3 3.29%→6.52% と全レーンで後者が1.5〜2倍。飛行帯のノーツblobは半径6〜11pxしかないので、31〜39pxの横ズレはノーツの大きさで埋まらない。

`--flick` は supervisor の既定オプション（`tools/ops/supervise_autolive.sh:18` の `TAP_OPTS="${I7_TAP_OPTS:---flick --auto-circles}"`）なので、**本番周回で常時この取りこぼしが起きている**。

**直し方**: 飛行線を計算する関数を1つに切り出し、検色点を SPAWN→レーン円の直線上に置く。ただし**ドロップイン不可**:
- `SPAWN→円` は約243px、`ARC→円` は約178px なので、同じ `FLICK_APPROACH_FRAC=0.65` では検色点が62px手前→85px手前へ大きく上流に動く
- 「0.65 で色が出る（白飛び前）」という較正と `FLICK_RED_MEMORY=0.35s` の前提が崩れる
- **飛行線に載せ替えると同時に FRAC を再較正するか、「円から一定px手前」という指定に変える**

同じ幾何は将来の「上流ROIによる予測発火」でも使えるので、共通関数化する価値がある。

**検証の所見（partial の範囲）**: 「SE では3レーンが箱外」は誤り（正方形ROIの角を無視した円近似による）。正しくは両機種とも外側2レーン。「事実上できていない」も全体としては言い過ぎで、`docs/README.md` 0.11 の実機記録（`--flick` で MISS 14→3, PERFECT 82→98）は「4レーン中2レーンが効いている」状態と矛盾しない。影響は赤ノーツ（稀）の外側2レーンでフリックが出ずタップ＝部分点になること。

---

### M-7: `note_engine.detect_notes` の全画面 `np.where` が実行時間の8割を占める

- **対象**: `tools/note_engine.py:66-81`（特に73行 `ys, xs = np.where(lbl == i)`）
- **判定**: confirmed

**問題**: ブロブごとに**フレーム全体のラベル配列を走査**して色平均を取っている。`stats[i]` のバウンディングボックスは取得済みなのに使っていない。加えて `mn = frame_rgb.min(axis=2)` と `morphologyEx` を帯（y 0.05〜0.62 = 334行中163行）ではなく**フレーム全体**に掛けている。

実測（`tests/corpus_raw/gameplay` 78枚, 529x334, 各3周）:

| 段階 | 累積時間 |
|---|---:|
| `min(axis=2)` | 1.03 ms |
| +mask | 1.03 ms |
| +morphologyEx | 1.06 ms |
| +connectedComponentsWithStats | 1.32 ms |
| **+`np.where` ループ** | **7.99 ms** |

**`np.where` ループ単独で 6.67 ms（全体の84%）**、連結成分検出自体は 0.26 ms しかない。671x348 では 10.7〜11.4 ms。

**影響**: `docs/note-engine-dev.md` は track エンジンが使い物にならない根本原因を「毎フレーム全画面の連結成分検出を行い重い」と結論づけ、「別スレッド化などの大きな最適化が必要で payoff は不確実」としているが、**この診断は誤り**。数行の書き換えで解決する。現状 `--predict` を有効にすると 27ms のループに約11ms が乗り、FPS が 37→26 程度に落ちる。

**直し方**:
```python
# (1) bbox に限定（出力は完全一致、6.67ms → 0.076ms）
x, y, w, h = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], \
             stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
sub = frame_rgb[y:y+h, x:x+w]
m = (lbl[y:y+h, x:x+w] == i)
rgb = sub[m].mean(0)
```
```python
# (2) 帯でクロップしてから min/morph/CC を掛ける（座標は後で y0 を足す）
```
両方で **7.99 → 0.82 ms（9.8倍）**、671x348 では 10.7 → 1.04 ms。

**注意**: (2) の帯クロップは現行と**厳密等価ではない**。現行は帯外を0にして全画面に `MORPH_CLOSE` を掛けるため境界行のブロブが削られるが、クロップ版は境界値扱いが変わって削られない（78フレーム中17フレームで blob 集合が変化）。数px パディングしてクロップすれば解消する。(1) 単独は完全等価で削減量の82%を占めるので、**まず (1) だけ入れるのが安全**。

**検証の所見**: 「この誤診のせいで `--predict` が塩漬け」は言い過ぎ。同 doc は「中空リングの検出漏れ」「報告ゲートが厳しい」も併記しており、recall の問題は速度を直しても残る。

---

### M-8: `--predict` / `--holds` でホールド中に gameplay を抜けると LeftMouseDown が解放されない

- **対象**: `tools/autolive.py:908-924`（down 発行）、`tools/autolive.py:1126-1132`（`run()` の finally）、`tools/autolive.py:1413-1416`（状態遷移時のリセット）
- **判定**: partial

**問題**: 解放は `_gameplay_timing` の冒頭ブロックでしか行われないのに、`hold_idx` / `hold_release_at` は状態遷移リセットにも `run()` の finally にも含まれていない。`run()` の finally は `caf.terminate()` だけ。ホールド中に ESC 長押し・`GAMEPLAY_TIMEOUT` break・`--max-seconds` 到達・Ctrl-C のいずれかが起きると `up` が送られない。

**影響**: macOS 側の左ボタンが押されたままユーザーに返る。マウスを動かすと `LeftMouseDragged` になり、デスクトップの範囲選択やウィンドウのドラッグが発生する（物理クリック1回で復帰する）。窓は1ホールド最大 `HOLD_MAX_SEC = 2.5` 秒。

**直し方**:
```python
def _release_hold(self):
    if self.hold_idx is not None:
        self._press(*self.content_to_screen(*CIRCLES[self.hold_idx]), "up")
        self.hold_idx = None
        self.hold_release_at = None
```
を (a) 状態遷移リセット（1406行付近）で `state != "gameplay"` のとき、(b) `run()` の finally（dry_run でなければ）、(c) 各 watchdog の break 直前、で呼ぶ。

**検証の所見（partial の範囲）**: `--predict` / `--holds` は**いずれも既定 OFF**（`action="store_true"`）で、`tools/ops/` のどのスクリプトも渡していない。既定の周回運用ではこのコードパスに到達しない。また「ライブ終了直後に Result へドラッグしてリザルト送りが効かない」は誇張 — 次に呼ばれる `_click_screen` が MouseMoved→Down→**Up** を出すので1クリックでボタン状態は解消し、Result 送りは0.35秒間隔でリトライされるため自己回復する。

---

### M-9: `match_multiscale` が当選スケールを捨て、PAUSE ダイアログのポップイン中に再開ボタンを外す

- **対象**: `tools/autolive.py:356-371`（`match_multiscale`）、`tools/autolive.py:628-630`（`click_anchor`）
- **判定**: partial

**問題**: `match_multiscale` は `SCALES = [0.8, 0.86, 0.93, 1.0, 1.08, 1.18]` を試して最良スコアの**中心座標だけ**を返し、当選スケールを捨てる。`click_anchor` は `pos_px + off` と固定 px を足すだけ。

実機コーパス `tests/corpus_raw/pause/` の37枚で `match_in_box` + `ANCH_RESUME` をシミュレートし、青い「再開」ボタンの bbox を色抽出して命中判定した結果:

| 結果 | 枚数 | 詳細 |
|---|---:|---|
| HIT | 25 | s=1.0 でマッチ、click(364,269)、btn y241..270（**下端まで1px**） |
| MISS | 7 | s=0.8〜0.86 でマッチ、dy=+18〜+60px |
| ボタン未描画 | 5 | ダイアログが小さすぎる |

原因は機種差ではなく **PAUSE ダイアログのポップインアニメーション**（同一SE機でボタン中心が (335,235)→(352,248)→(363,255.5) と拡大していく）。

**影響**: PAUSE 復帰が約0.5〜1.5秒遅れ、その間のノーツを取りこぼす。次の判定周期（クリック後 sleep 0.4 + `DARK_RECHECK_SEC` 0.7）でダイアログが等倍に落ち着けば命中するので、復帰不能にはならない。

**直し方**:
1. `match_multiscale` / `match_best` / `match_in_box` の戻り値に当選スケール `s` を追加し、`click_anchor(pos, off, scale)` で `pos + off*s` を押す。
2. **より効く対策**: SE で s=1.0 命中時でも click y=269 に対しボタンが y241..270 = **下端から1px**しか余裕がない（`ANCH_RESUME` を iPhone16 基準で 161→176 に変えた副作用）。`ANCH_RESUME` の y を両機種の中間に取り直す方が現実的な脆さに効く。
3. 各アンカーについて「マッチ中心からの着弾点がテンプレ由来の想定矩形内」を確認する unittest を追加。

**検証の所見（partial の範囲）**:
- 「機種差で1.18倍」は成り立たない。iPhone16 見出し(337,91)→再開(437,267)=(100,176)、SE 見出し(264,93)→実測ボタン中心(363,255.5)=(99,162.5)。**dx は 100 vs 99 でほぼ同一、dy だけ 13.5px 違う** = 相似拡大の関係ではない。よって `pos + off*s` を入れても機種差は直らない。
- 「variant のクロップサイズが違うのでマッチ中心の意味が変わる」も否定。`life_short.png`(125x16) と `life_short_event.png`(184x26) の中心は 0.5px しかずれない（同心）。
- 「アシストアイテム消費」「ステラ誤爆」には至らない（`liveassist` / `lifeshort` は閾値0.85と高く、実測はすべて s=1.0）。pause だけ閾値0.78が低いためアニメ中スケールを拾っている。

---

### M-10: 座標定数の3世代が同居し、20個の座標定数が未参照のまま残っている

- **対象**: `tools/autolive.py:86-149, 247-252`
- **判定**: confirmed

**問題**: 座標の表現方式が3世代同居している。

| 世代 | 定数 | 現役か |
|---|---|---|
| ウィンドウ相対 | `P_*`（88-118） | `P_EASY_TAB` / `P_CARD_DISMISS` の2つだけ |
| 中央+pxオフセット | `OFF_*`（124-136） | `OFF_LIFE_CONFIRM` / `OFF_RESULT_ADV` / `CLOSEX_OFFSETS` のみ |
| テンプレマッチ位置+pxオフセット | `ANCH_*`（141-149） | 8個すべて現役 |

未参照は `P_DOWNLOAD, P_REPLAY_YES, P_RANKUP_X, CLOSEX_CANDIDATES, P_RESULT_ADV, P_NEXT, P_FRIEND_FIRST, P_STORY_NO, P_START, P_MENU_SAFE, P_KINAKO_RECOVER, P_LIFE_CONFIRM_X, SE_GAME_CENTER, OFF_RESUME, OFF_REPLAY_YES, OFF_DOWNLOAD, OFF_STORY_NO, OFF_KINAKO, OFF_RANKUP_X, OFF_MENU_SAFE` の20個＋調整値 `TRACK_FORGET_SEC`。`P_RESUME` は本番からは未参照で `tools/probes/` の5本だけが使っている。

加えて **86-87行のセクション見出しが誤り**（「すべて『ゲーム内容矩形』相対の小数」と宣言しているが、直下の `P_DOWNLOAD` 等は個別コメントで「窓相対・実測」と書かれ、実際に生きている2つも `click_window` で窓相対として使われている）。

**なぜ危険か**: 死んだ値が docs と永続メモリに「正」として複製されている。`P_KINAKO_RECOVER = (0.644, 0.508)` と `P_LIFE_CONFIRM_X = (0.78, 0.41)` は `docs/navigation.md:191,203,205` とユーザーの永続メモリ `i7-life-recover-kinako.md` に「これを使う」と明記されているが、実際の挙動は `ANCH_KINAKO` と `OFF_LIFE_CONFIRM` が決めている。しかも「ステラの回復は下段(0.644,0.69)。絶対にクリックしない」という**安全上もっとも重要なコメントが死んだ定数側にぶら下がっている**。

`CLAUDE.md` 自体もこの混乱の被害を受けている（「menu安全タップは中央オフセット(`click_center_off`/`OFF_*`)のまま」と書くが、menu ハンドラはクリックを一切しない）。

**直し方**:
1. 未参照20個＋`TRACK_FORGET_SEC` を削除（履歴に残るので消してよい）。
2. `P_RESUME` は `tools/probes/` の5本（`hidmove_test.py:34`, `pause_monitor.py:19`, `focus_state_monitor.py:45`, `trigger_test.py:79`, `focus_probe.py:53`）が参照しているので、probes 側で座標リテラルをインライン化してから削除する。
3. 残す定数は座標系を名前で明示する（`WINFRAC_EASY_TAB` / `CONTENTFRAC_ARC_CENTER` 等）か、方式ごとに節を分けて `# [anchor]` `# [center-offset]` `# [window-frac]` のタグを付ける。
4. 86-87行の見出しを実態に合わせて修正する。
5. `docs/navigation.md` と MEMORY の記述を「実装は `ANCH_KINAKO` / `OFF_LIFE_CONFIRM`」に更新する（C-1 の作業と同時）。

---

### M-11: `AutoLive` が6つの責務を1クラスに抱え、`detect()` の抽出が未着手

- **対象**: `tools/autolive.py:417-1416`
- **判定**: partial

**問題**: `AutoLive`（`__init__` 418-481、`detect` 1009-1114、`_loop` 1134-1416 = 283行）が、座標変換 / 合成入力 / 画面分類 / 打鍵エンジン / 円キャリブレーション / FSM+watchdog を1つの `self` に抱えている。実害:

- **外部ツールが分類だけ使えない**: `AutoLive.__new__(AutoLive)` で偽インスタンスを作るハックが4箇所（`tools/ops/result_log.py:67`、`tools/ops/run_until.sh:27` の埋め込み Python、`tests/test_detect_dialogs.py:22`、`tests/test_roi_scale.py:21`）。
- **その代償が本体に入り込んでいる**: `tools/autolive.py:1095` の `getattr(self, "suppress_cardx_until", 0.0)` に「detect() は result_log 等の外部ツールからも `__new__` 生成のインスタンスで呼ばれるため」というコメント付きの防御がある。`self.suppress_cardx_until = 0.0`（458行）と同じコミットで入っており、**属性を足す側が最初から外部呼び出しを気にして書いている**。
- **残骸が積み上がる**: `formation` の二重判定（1089行と1112行、後者は決定的に到達不能）、到達不能な `"download"` state（1343行）。
- **fail-closed の連鎖**: `run_until.sh:27` の `connected()` は `except Exception: sys.exit(1)` なので、`detect()` が新属性を要求すると **AttributeError が「ミラーリング切断」と誤診**され、無人運用が一晩空回りする（L-O4 参照）。

**直し方**（段階2の設計。`docs/superpowers/specs/2026-07-30-project-cleanup-design.md` が予定している分割）:

`tools/i7/` パッケージを新設し、依存が一方向になるよう切る:

| 新モジュール | 依存 | 移すもの（現行行） |
|---|---|---|
| `geometry.py` | numpy のみ | `detect_content_rect`(333-353), `content_to_screen`(484-491), `pixel_to_screen`(493-494), `game_center_px`(617-622), アンカー座標計算(624-630)。win/content を**引数で受ける自由関数**に |
| `screens.py` | データのみ | `TEMPLATES`(217-253), `ANCH_*`(141-149), `OFF_*`(124-136), `CLOSEX_OFFSETS`, `P_EASY_TAB`, `P_CARD_DISMISS` |
| `recognize.py` | cv2/numpy + screens | `load_templates`(282-297), `match_*`(300-414), `detect_card_x`(310-330), `detect()` 本体(1009-1114) を `classify(frame_rgb, templates, *, now, dark_state, suppress_cardx_until) -> (state, evidence)` の自由関数へ |
| `actuator.py` | Quartz + geometry | `_click_screen`(497-515), `_press`(592-602), `click_*`(604-630)。`_click_screen_exp`(517-590) は probes へ退避 |
| `tapper.py` | geometry + actuator + note_engine | `RoiTapper`(633-939, 975-982) / `TrackTapper`(941-973)。共通IF `step(frame, now)` / `set_circles(circles)`。circles はコンストラクタ引数（M-12 のグローバル廃止と同時） |
| `calibration.py` | note_engine | `_autocal_*`(736-794)。`CIRCLES` を書き換えず**補正結果を返す**だけにする |
| `watchdog.py` | — | 停滞判定と `/tmp/i7dbg` 保存。現在 `_loop` に「now-X>Y ならスクショ保存して break」が**7箇所**コピペされている（1181, 1211, 1259, 1275, 1295, 1380, 1397） |
| `autolive.py` | 上記すべて | FSM と CLI のみ。`_loop` の if/elif を `HANDLERS = {"pause": self._on_pause, ...}` に |

**移行順**: `geometry` → `recognize`（**この時点で M-12 のコーパス回帰テストを先に入れる**）→ `actuator` → `tapper`（ここで CIRCLES をインスタンス化）→ `calibration`/`watchdog` → FSM。各段階でテストが緑のまま進められる。

**検証の所見（partial の範囲）**: 「6層が癒着」は誇張。`load_templates` / `match_*` / `detect_card_x` / `detect_content_rect` は**すでに module-level の自由関数**でクラスの外にある。クラスに癒着しているのは `detect()` 本体だけで、しかも `detect()` が参照する self 属性は `templates` と `_last_dark_check` の2つ（＋getattr 防御付きの `suppress_cardx_until`）のみ。自由関数化は数行の機械的作業。また「この癒着のままでは分割の最初の一手が決まらない」も誤りで、設計書自身が「最初の一手 = corpus を使った `detect()` 回帰テストの整備」と決めている（未着手なだけ）。

---

### M-12: `detect()` のコーパス回帰テストが存在しない

- **対象**: `tests/test_corpus_smoke.py:14-26`、`tests/test_detect_dialogs.py`
- **判定**: partial（テストギャップは実在。ただし**提案どおりに書くと有害**）

**問題**: `tests/corpus_raw/` には14ディレクトリ・507枚の実機フレームがあるが、これを使う唯一のテスト `test_corpus_smoke` は `NE.detect_notes` / `NE.detect_circles` が「クラッシュしないこと」だけを確認しており（戻り値を捨てている）、**本体の `AutoLive.detect()` は一度も通していない**。`detect()` を通すテストは `tests/test_detect_dialogs.py` の手選び2枚（story / resumelive）のみ。

`detect()` の判定順とテンプレ閾値はこのプロジェクトで最も壊れやすい部分（イベント装飾でテンプレが崩れて停止、という事故が MEMORY に記録されるほど繰り返されている）なのに、閾値を1つ動かしたときに何が壊れるかを機械的に知る手段が無い。

**そのまま `assertEqual(detect(frame), dirname)` を書いてはいけない**:

- `tests/corpus_raw` のラベルは `tools/ops/corpus_collector.py` が `detect()` 自身の出力で付けた**自己ラベル**。「61/61 一致」は決定的な関数に同じ入力を入れ直しただけのトートロジー。
- 実際に誤ラベルが混ざっている:

| ファイル | 実体 | 現ラベル | 原因 |
|---|---|---|---|
| `menu/003257_enter.png` | 楽曲選択画面（NEXT・EASY/NORMAL/HARD タブが写る） | `menu` | songselect=0.84 対 閾値0.85 の取りこぼし |
| `menu/093734_enter.png` | ライブ中（COMBO/PERFECT が出ている） | `menu` | bright=65.6 で `DARK_THRESH=65.0` をわずかに超えた |
| `menu/095238_enter.png` | 同上 | `menu` | bright=67.0 |

これらを期待値として固定すると、songselect 閾値を 0.83 に下げる**正しい修正**や `DARK_THRESH` を引き上げる修正が「回帰した」と誤検知されてブロックされる。

**直し方**:
1. **目視で ground truth を確認したサブセット**を `tests/frames/<state>/` に **git 管理下で**コミットする（既に `tests/frames/` に2枚コミットする前例がある）。各クラス3〜5枚、`corpus_raw` 全体は現状どおり ignore して「任意の追加検証」に留める。
2. `detect()` は明るいフレーム1枚あたり約0.5〜0.93秒かかるので、全枚ではなくクラス毎サンプリング（60枚で約1分）にする。
3. **フレームごとに fresh インスタンスを使うか `_last_dark_check = 0.0` を入れる**。`DARK_RECHECK_SEC = 0.7` の間引きがあるため、1つのインスタンスを使い回して連続 detect すると暗い pause フレーム（37枚中4枚）が間引きに当たって `gameplay` を返しフレーキーになる。
4. コーパスに存在しない `story` / `resumelive` / `eventresult` / `liveassist` / `rankup` のフレームを追加取得する（**事故が実際に起きた画面が1枚も無い**）。
5. 判定順の不変条件をテストで固定する（`lifeshort` は cardx/closex より前、`formation` は cardx より前、`eventresult` は result より前）。

---

### M-13: LIFE 回復（きなこパン限定・ステラ厳禁）の回帰ガードが1本も無い

- **対象**: `tools/autolive.py:1187-1189`、`tests/`
- **判定**: partial（C-1 の再発防止策）

**問題**: `grep -rn "lifeshort|ANCH_KINAKO|OFF_LIFE_CONFIRM|life_short" tests/` は**ヒット0件**。`tests/*.py` 内の `ANCH_` 参照は `test_detect_dialogs.py:66-67` の `ANCH_RESUME_YES` のみ。プロジェクトの絶対規則1（ステラを絶対に使わない）にテストが存在しない。

**直し方**（C-1 とセット）:
1. `tests/frames/` に **きなこパン枯渇時**の lifeshort フレームをコミットする（`tests/corpus_raw/lifeshort/105609_enter.png` がまさにそれ）。
2. 検証項目:
   - `detect()` が `lifeshort` を返す
   - **着弾点がステラ「回復」ボタン矩形に入らない**（失敗メッセージに「ステラ側へ落ちる」と明示）
   - きなこパン行が存在する通常フレームでは、着弾点がきなこパン「回復」ボタン矩形の内側にある
3. 実フレームに依存しない静的アサートも足す: 全 `life_short*` バリアントのマッチ中心が相互に数px以内であること（クロップずれの検知）。
4. **イベント装飾版の lifeshort フレームを新規取得する**。現在のコーパス3枚はすべて非イベント版で、「新バリアントを足したらマッチ中心が動く」という将来のリスクは既存資産では捕捉できない。

**検証の所見（partial の範囲）**: 通常時（きなこパン行が存在する場合）の着弾点は実測3枚で window相対 y=0.509〜0.521 とステラ行(0.69)から60px以上離れており正常。既存2バリアント（`life_short.png` / `life_short_event.png`）のマッチ中心も1px以内で一致しているため、「バリアントを足すとマッチ中心が動く」という機構は現時点では未発現。

---

### M-14: `assets/prompts/event_navigation.md` のブースト設定UI記述が実機と違い、オートOFF確認が欠落

- **対象**: `assets/prompts/event_navigation.md:30-31`
- **判定**: partial

**問題**: 手順表 #4 は「倍率ボタンを押すごとに ×1→×2→×3 と巡回する UI」と書いているが、**実機にそんな UI は存在しない**。実仕様（`docs/navigation.md` (A) 節）は、楽曲選択下部の「ブースト◯倍／オート◯◯」パネル (0.55,0.89) をタップして**設定ダイアログ**を開き、ラジオボタン（3倍 = (0.55,0.26)）を選んで OK (0.62,0.87) を押す。

さらに `grep -rn "オート" assets/prompts/` は**0件** — 同じダイアログで設定するオートライブについて、prompts 側は一言も触れていない。`CLAUDE.md` 絶対規則5は「周回開始時は毎回、楽曲選択下部パネルが『ブースト 3倍／**オート OFF**』であることを確認してから START する（ユーザーは今後これを指示しない。言われなくても必ず確認する）」と定めている。しかも `docs/navigation.md:158-160` に「2026-07-31 の検証でゲーム側設定が『オート ON』のまま残っている」という警告がある。

**影響**: 前回の設定が残ったままオート ON でライブが始まると、1ライブにつきブリンドリンクを3個消費する（在庫201個なら約67ライブで枯渇）。

**直し方**: #4 を「楽曲選択下部の『ブースト◯倍／オート◯◯』パネルをタップして設定ダイアログを開き、**ブースト=3倍・オートライブ=OFF** の両方を選んで OK を押す。パネル表示が『ブースト 3倍／オート OFF』になったことを確認するまで NEXT しない」に書き換える。「最重要ポリシー」節に「オートライブは絶対に ON にしない」を追加。実測座標（529×334 と 671×348 の両方が `docs/navigation.md` (A)(B) にある）を手順表に転記して座標探索を不要にする。

**検証の所見（partial の範囲）**: 消費されるのはゲーム内消耗品（ブリンドリンク）であって課金アイテム（ステラ）ではないため critical ではない。また `event_navigation.md` はコードから自動実行される経路が無く（`grep -rn event_navigation --include=*.py --include=*.sh` は0件）、人間が同席して起動する暫定運用。設定ダイアログ内に購入導線は無い。

---

### M-15: `docs/operations.md:25` の「1周あたり 約83秒」が実測（中央値130.5秒）と乖離し、docs 内部でも矛盾

- **対象**: `docs/operations.md:25`、`docs/device-findings.md:244`
- **判定**: confirmed

**問題**: 「到達している水準」表が「1周あたり | 約83秒」、3.3FPS修正の結果表も「128秒 → **83秒**」としている。しかし同じ `docs/device-findings.md:209` は「判定376フレーム / **115秒** = 3.3 FPS」と115秒で計算し、`docs/screen-transitions.md:21` も「ライブ中 gameplay ── 約115秒」。**ライブ本体が115秒なら1周が83秒になることは物理的にありえない。**

実測（`/tmp/i7_autorun.log`、再起動をまたぐ区間を除外）:

| 指標 | n | median | 範囲 |
|---|---:|---:|---|
| クリア間隔（=1周） | 265 | **130.5s** | p25=128.9 / p75=136.0 |
| ライブ本体 | 49 | **115.8s** | p10=114.7 / p90=119.5 |
| 判定フレーム/ライブ | 225 | 4301 | → 4301/115.8 = **37.1 FPS** |

**83秒という値はどのログにも存在しない**（修正前 run8.log は 122.6〜151.0s、修正後 run9.log は 126.0〜142.3s）。つまり「128秒 → 83秒」という改善行そのものが誤り（曲長は固定なので1周が短くなるはずがない）。

**影響**:
- 8時間の計画で 28,800/83 ≒ 347周と見積もるが実際は220周（約1.6倍過大）。LIFE・きなこパンの必要数も同倍率で外れる。
- 正常稼働中のログで130秒を見た運用者が「劣化した」と誤検知し、不要な調査に入る。
- `CLAUDE.md:46` の「ループ周波数 = 判定フレーム ÷ ライブ長」に分母83秒を代入すると 4301/83 = 51.8 FPS となり、docs 記載の正常域「26〜37 FPS」を超えて誤った切り分けに進む。

**直し方**: 「1周あたり 約130秒（うちライブ本体 約115〜120秒、リザルト処理 約12秒）」へ修正。`device-findings.md:244` の修正前/修正後表からは「1周あたり」の行を削除するか、83秒の出所不明を注記する。`CLAUDE.md` の FPS 診断手順に「分母はライブ本体≒115秒（1周130秒ではない）」を明記する（`assets/prompts/supervisor_loop.md:60` は既に正しく「約115秒」と書いている）。

---

### M-16: `docs/screen-transitions.md` §3.7 とコード内コメントが「曲は変更しない」のまま

- **対象**: `docs/screen-transitions.md:124-125`、`tools/autolive.py:1307-1308`
- **判定**: confirmed

**問題**: §3.7 は「楽曲選択: … **曲は変更しない**（曲リストはタップせず現在選択中の曲のまま進める＝ユーザー要件）」と書いている。実装は逆で、`tools/autolive.py:1313-1319` が `songdaz` テンプレで一覧行を探してタップし、Don't Analyze Me を選ぶ。`docs/navigation.md` の「周回時の選択（2026-07-31 ユーザー指定・実装済み）」は正しく記載しており、2つのドキュメントが正面から矛盾している。

**さらに悪いことに、同じ古い主張がコード内コメントにも残っている**:
```python
# tools/autolive.py:1307-1308
# ユーザー要件: 楽曲は変更しない。曲リスト（左側）は絶対にタップせず、現在
# 選択中の曲のまま進める。ここで触るのは EASY タブ（右下・難易度）と NEXT のみ。
```
その2行下に「# ユーザー要件: 毎回「Don't Analyze Me」を選ぶ」があり、直下の実コードは実際にタップしている。

**影響**: 将来のセッション（`CLAUDE.md` の指示どおり screen-transitions.md を先に読む LLM copilot を含む）が `songdaz` 選択ロジックを「ユーザー要件違反の混入コード」と判断して削除しうる。削除すると連戦終了後に効率の悪い曲（Ache 約103ノーツ）のまま周回し、イベントpt効率が落ちる。エラーも安全停止も出ないので無人運用中は気づけない。

**直し方**: §3.7 を「**毎回 Don't Analyze Me を選ぶ**（`songdaz` テンプレで一覧行を探してタップ。見つからなければ曲を変更しない＝安全側）」に修正。フレンド選択にも「必ず最上段（`match_topmost`）」を明記（現在 §3.7 も §2 の表も落としている）。`tools/autolive.py:1307-1308` の古いコメントを削除する。曲が変わったときに撮り直すテンプレ（`assets/templates/song_*.png`）への参照も付ける。

**原因**: `screen-transitions.md` の最終更新は `f59dc8d`（2026-07-30 23:38）で、songdaz を入れた `22ac8a0`（2026-07-31 16:50）より前。

---

## Low

実行時の誤動作を伴わない、または限定条件下でのみ軽微な劣化が生じるもの。カテゴリ別に列挙する。

### 安全・堅牢性（実行時。ただし watchdog で有界）

| ID | 対象 | 概要 | 対処 | 検証の範囲 |
|---|---|---|---|---|
| L-S1 | `tools/autolive.py:1036-1054` | 暗い画面は pause/songselect 以外すべて `gameplay` と断定。未知の暗い画面で `_keepalive` が約1.6回/秒 × 最大240秒（計約390回）の盲目タップを出す | (a) 暗い分岐の間引き照合に `lifeshort` / `cardx` も含める (b) gameplay 断定に「ライブHUD が見える」positive check を足す | 「毎フレーム4点・1万回規模」は**誤り**（`note_baseline` が初回フレームで固定され発火しない）。実測427枚で `DARK_THRESH=65` を下回る非gameplayは pause 4枚のみ。ショップ/課金画面が暗くなる根拠は無い |
| L-S2 | `tools/autolive.py:994-1002, 497-515` | 前面判定は `_keep_front(interval=0.4)` にしか無く、`_click_screen` 側にガードが無い。最大0.4秒の空白がある | `_click_screen` 先頭で `_mirror_is_front()` を確認（実測コスト 0.003ms/回なので安価） | 漏れの前提は「前面喪失」ではなく「**クリック点の重なり**」。主犯である通知バナーは `frontmostApplication` を変えないので、提案のガードでは防げない。0.4秒で出るクリックは理論最大8発（`NOTE_DEBOUNCE_SEC=0.18` のため） |
| L-S3 | `tools/autolive.py:310-330, 1250-1267` | `cardx` の色条件が緩く、news / title / `prev_result_dialog` / `lifefull_freeze` を誤検出する。閉じる操作が固定座標 `P_CARD_DISMISS` | 色条件を「連続した1本の帯」に限定（H-2 と同一の修正）。`prev_result_dialog` に専用テンプレを追加 | 「右上を70回連打して課金導線を踏む」は誇張。実測で1反復1〜2.5秒なので25秒で10〜20回、着弾点は news では**正しい×の上**、title では課金要素の無いアイコン帯。`STUCK_STOP_SEC` の上限も既にある |
| L-S4 | `tools/autolive.py:740-752` | `_load_cached_circles` に値域検証が無い。手編集/破損で枠外値が入ると `content_to_screen` が窓外を返す | 読込・保存の両方で `0.0 <= x,y <= 1.0` を検証。`content_to_screen` 側で `self.win` 矩形にクランプ | 自動生成キャッシュに異常値は入らない（`consensus_circles` が prior から `tol=0.10` 内の中央値しか返さない）。実害は手編集/破損時のみ。しかも `--auto-circles` は既定 OFF |
| L-S5 | `tools/autolive.py:740-752` | `except Exception: pass` でキャッシュ読込失敗が無言 | `except Exception as e:` にして1行ログ | 破損時は `_save_cached_circles` 側が同じ例外で「保存に失敗」を毎回ログするため手掛かりは残る。実質 nit |
| L-S6 | `tools/ops/recover_freeze.py:132-142` | STEPS に一致しないフレームが2回続くと画面内容を見ずに `click_frac(0.5, 0.55)` を送る | (a) `title_tap` があるのでフォールバックの中央タップ自体を削除 (b) 残すなら「画面がほぼ一様（ロード中）」に限定 | 「3秒おき」は誤りで実際は12〜20秒に1回・300秒で最大15〜20回。300秒でタイムアウトして `/tmp/i7_freeze_unrecovered` を作り人間に投げるので無限ではない。「バナー中央は購入導線」は裏付けなし（実機のダイアログボタンは y≈0.76） |
| L-S7 | `tools/ops/pause_guard.sh:30-31` | pkill パターンがパスを含まず緩い。`run_until.sh` を止めないので併用時にガードが無効化される | パスを含める（ただしこれだけでは worktree 問題は解決しない — `run_until.sh` が `cd` して相対パス起動するため argv が同一になる）。H-4 の停止フラグ方式が本命 | 「自分自身を巻き込む」は誤り（argv が一致しない）。「supervisor→autolive の順が危険」も誤り（逆順にすると supervisor が8秒後に再起動してしまう） |

### 打鍵精度・性能

| ID | 対象 | 概要 | 対処 | 検証の範囲 |
|---|---|---|---|---|
| L-A1 | `tools/autolive.py:164-173, 662-674` | `ARC_CENTER=(0.49,0.50)` が実測スポーン `SPAWN=(0.50,0.06)` と126〜133px 食い違い、lead 方向・`_flick` の外向き方向が真の飛行方向から18〜31°ずれる | 基準点を `SPAWN` に統一する（lead機構の廃止**ではない**）。`_roi_scale` が根拠にする「移動距離1.34倍差」も ARC 基準ゆえの誤りで、SPAWN基準の実距離は4円とも243〜246pxでほぼ等距離 | 「lead は意図と逆に働く」という中核主張は実フレームで**反証**（lead=0.02 だけが発火したケース3件、lead=0 だけは0件）。lead=0 にすべきではない（`0.015 は早撃ち不足で PERFECT 低下`という実測記録がある）。有効成分は cos(18.5〜30.9°)=0.86〜0.95 で無駄は5〜14% |
| L-A2 | `tools/autolive.py:975-982, 936-937` | `_keepalive` が「害のない円」と称して**実判定円**を叩き、`note_last_tap` を記録しないため自分の波紋で誤発火しうる | タップ先を判定に絡まない中央ダミー位置 (0.49,0.93) に移す。keepalive 回数を `tap_count` とは別に集計してログに出す | 「tap_count が水増しされる」は**誤り**（`_keepalive` は `tap_count` に触らない）。「デバウンスも効かず二重打鍵」は符号が逆（記録しないおかげで直後の本物のタップが通る）。実害は「自分の波紋で1回余分に発火し、その後0.18秒そのレーンが不感になる」こと |
| L-A3 | `tools/autolive.py:1036-1054` | ライブ中に0.7秒ごと約15ms(SE)/20ms(671x348) のテンプレ照合ヒッチ | 現状維持を推奨 | 「明るさフロア57を入れる」という提案は **1052行の songselect 救済も同時に止める**（コメントは「ジャケット/KEEP OUTテープで mean≈61 まで暗くなる」ため意図的にフロア50を置いたと明記）。楽曲選択で停止する退行の方が20msの遅延より重い |
| L-A4 | `tools/autolive.py:939` | `_gameplay_timing` 末尾の `time.sleep(0.005)`（実測7.4ms）がフレーム時間の19〜27%を占める | 削るなら**必ず `NOTE_ROI_LEAD` を再測定してから**（lead=0.02 は現在のFPS前提の較正値）。`--holds` 併用時は `HOLD_SUSTAIN_FRAMES=14` がフレーム数ベースなので FPS 上昇で 0.29s 相当になり波紋誤検出が再発しうる | 利得は量子化平均遅れ 13.5→11ms の 2.5ms で、`mss.grab` のばらつき（17〜27ms）に埋もれる規模 |
| L-A5 | `tools/autolive.py:850-889, 899-915`, `tools/note_engine.py:337-339` | `TypeForecast.consume(lane, now)` が `now` を一切見ず「eta_at 最小」を返す。遠未来 eta のエントリは `_expired` で消えず永久に残る。consume 後も次フレームの `update` で復活し二重 consume できる | (a) `consume` に許容窓（`abs(eta_at - now) > 0.25` は返さない） (b) 消費済み track id の短時間ブラックリスト (c) `eta > 1.5s` の予報は登録しない | 「ホールド中も他レーンを打てばよい」という提案は**技術的に不可能**（`CGWarpMouseCursorPosition` による単一ポインタ方式なのでマルチタッチを合成できない）。`--predict` は既定 OFF・実機検証待ち |
| L-A6 | `tools/autolive.py:1055-1114` | 明るい画面の `detect()` が実測933ms（menu）。1周あたり約6.3秒 = 7.6% の損 | (a) `formation` の二重照合（1089行と1112行、後者は到達不能）を削除して約42ms 回収 (b) 明るい側にも性能上限テストを追加 | 「watchdog の分解能が粗くなる」は**誤り**（停滞判定は純粋な実時間比較でサンプル回数に依存しない）。「十数秒」も過大（実測6.3秒）。「頻度順に並べ替え」は `lifeshort` 最優先という安全要件と衝突するので不可 |

### ops・可観測性

| ID | 対象 | 概要 | 対処 | 検証の範囲 |
|---|---|---|---|---|
| L-O1 | `tools/autolive.py:1180, 1213, 1261, 1277, 1297, 1398` | 停止時スクショ名がプロセス内経過秒のみで衝突し、同種障害は最新1枚しか残らない（cardx 停滞34回に対し5枚） | ファイル名の先頭に `time.strftime('%Y%m%d_%H%M%S')` を付ける。`/tmp/i7dbg` に世代上限を設ける | 「時系列が復元できない」は誤り。`/tmp/i7_autorun.log` に34件すべてが発生順に残り、supervisor ログには壁時計時刻がある。失われるのは画像のみ。しかも `gameplay_timeout_250/251/252.png` は md5 が完全一致（同種停止は同一フレームの反復） |
| L-O2 | `tools/ops/supervise_autolive.sh:10, 34` | `/tmp/i7_autorun.log` に壁時計時刻もローテーションも無い（現在 1.27MB・87セッション混在） | `autolive.log()` の出力に壁時計時刻を含める | **ローテーションは入れてはいけない**。`freeze_sentinel.sh` の `grep -c` 累積値差分が巻き戻り、フリーズ検知が機能しなくなる。セッション境界行（`自動周回を開始`）は既に存在し、下流ツールは誤動作していない |
| L-O3 | `tools/ops/run_until.sh:17-38, 53-58` | `connected()` が切断・内部エラー・`state=="menu"` をすべて rc=1 に潰し、「ミラーリング切断中」と誤ったログを出す | 例外種別で終了コードを分ける（切断=1 / 内部エラー=2）。`2>/dev/null` を外して stderr を $LOG に流す | 「永久待機」は誤り（TARGET で必ず終了）。「30秒ごとに永久にログ」も誤り（`waiting` ガードで1回だけ）。`__new__` の属性依存も既に `getattr` 規約で手当て済み。誤報の主因は例外ではなく `state=="menu"` の方 |
| L-O4 | `tools/ops/run_until.sh:17-38` | `connected()` が明るさを見ないので、横向きのまま真っ黒（Mac 画面ロック等）だと「接続中」と誤判定しうる | `connected()` に明るさチェックを追加。ただし単発フレームでなく数秒の連続性を見ること（ライブ→リザルト間の暗転で誤判定しないため） | 実測26件の空回りの原因ではない（切断時のウィンドウは縦長 318x701 でガードに掛かる）。より価値があるのは autolive 側の early-exit（mean≈0 が数秒続いたら240秒待たずに切断と判定） |
| L-O5 | `tools/ops/result_log.py:27-41, 65-103` | リザルトを画像でしか残さず、実測で4〜6割を取りこぼす（`/tmp/i7dbg/reslog.log` で検出3回中2回が見送り）。設定・git sha・打鍵回数と紐付かない | 取りこぼしを減らす（0.4秒ポーリング + 重い全画面 detect のため autolive の0.35秒送りに追いつけない）。数値化は `assets/prompts/result_ocr.*` として設計済み・未実装 | 「最初のフレームを保存する方が確実」は**誤り**（リザルトは数値がカウントアップするので最終値でない）。`ROI_SCALE_BY_DISTANCE` は n=1 のまま既定OFFにされている（`/tmp/i7dbg/results/roi_scaled/` に画像1枚のみ） |
| L-O6 | `tools/autolive.py:938, 850-889, 941-966` | `frame_count` が `_gameplay_timing` の**末尾**にしかないため、ホールド継続中の早期 return を通ったフレームが計上されない。ホールド開始も `tap_count` を飛ばす。`_gameplay_track` は両方とも加算しない | `frame_count` の加算を関数先頭へ移す。`taps / flicks / holds / keepalives / frames / fps` を分けてライブ終了ログに出す | 既定構成（predict=False / holds=False / engine=roi）では早期 return に到達せず、3.3FPS 問題を発見した計測は完全に正確 |
| L-O7 | — | 在庫（きなこパン）から周回可能時間を逆算する手順が docs に無い | `docs/operations.md` に実測消費率を追記。**「1個/周」ではなく実測 0.664個/周**（clears 280 / recovers 186）。1個で LIFE+20、EASY 消費15〜16 なので数周に1回スキップされる | 「毎周1個」という前提は誤り。`在庫 × 130秒` という式は消費率を1.5倍に見積もるため、そのまま書くと周回機会を取り逃がす |

### 保守性・テスト

| ID | 対象 | 概要 | 対処 | 検証の範囲 |
|---|---|---|---|---|
| L-M1 | `tools/autolive.py:945-949, 776, 971` | `--engine track` + `--auto-circles` は円座標キャッシュ未ヒット時に `AttributeError: 'NoneType' object has no attribute 'update'` で即死。加えて track は `note_engine.LANES`（補正前）をタップし `--auto-circles` の結果を無視する | Tracker 生成の条件を `if self._ne is None:` から `if self.tracker is None:` に変え、import と生成を分離。`Tracker(..., lanes=list(CIRCLES))` を渡し、`_dispatch_note` も `CIRCLES[a["lane"]]` を使う | 「必ず落ちる」は誤り（`.autocal_circles.json` にキーがあると `circles_calibrated=True` で autocal が走らずクラッシュしない）。`--engine track` は docs で「farming には使わない R&D プロトタイプ」と結論済み（recall ≈6%）。既定 `TAP_OPTS` にも含まれない |
| L-M2 | `tools/autolive.py:154-157, 748, 787-792` | `CIRCLES` がモジュールグローバルで in-place 書き換えされる。ライブ中に補正が成功しても `note_baseline` が再初期化されない | `self.circles` へインスタンス化し、書き換えを `set_circles(new)` 1本に集約。その中で `note_baseline` を再初期化する | 起動時のキャッシュ復元は問題なし（派生状態がまだ存在しない）。`note_hi_frames` / `note_last_tap` / `note_red_seen` のリセットは**不要または有害**（デバウンスを消すと二重タップを許す）。発生条件は「そのウィンドウ寸法での初回実行の1ライブ」のみで、EMA が0.6秒で追従するため通常は自己修復する |
| L-M3 | `tools/autolive.py:190, 722-734`, `docs/architecture.md:237` | `TRACK_FORGET_SEC` は定義のみで未参照。`_note_present` はどこからも呼ばれていないのに docs が実装として名指ししている | `TRACK_FORGET_SEC` は**削除**する（`acted.clear()` を実装するとクリア直後に同一ノーツを二重タップする退行になる）。`_note_present` は削除し、docs の記述を `_gameplay_timing` のみに直す | 「acted が無制限に増える」は量的に無視できる（set(range(10000)) で 0.5MB、12時間で1MB未満）。id は単調増加で再利用されないので誤判定も起きない |
| L-M4 | `tools/autolive.py:1089-1113, 1343` | `formation` の判定が2回あり後者は到達不能。`elif state in ("dldialog", "download")` の `"download"` は `detect()` が返さない残骸 | 1112-1113行と1343行の `"download"` を削除。あわせて docstring(1018-1024)・`tools/autolive.py:17-19`・`docs/architecture.md:218`・`docs/navigation.md:181` の陳腐化した判定順記述を実装に合わせる | 両方とも決定的に到達不能な no-op で挙動は変わらない。実害は未知メニュー画面での約42ms の無駄と、陳腐化した順序記述による誤誘導 |
| L-M5 | `tools/autolive.py:288-297, 1030-1034` | テンプレ欠損時、`load_templates` は warn を出してキーを dict に入れないが、`detect()` の `m(key)` は無条件アクセスするので KeyError で異常終了 | `load_templates` の最後に「`TEMPLATES` の全キーが揃っているか」を検証し、欠損なら起動時に `RuntimeError`。`tests/test_templates.py` に「全17キーが1枚以上ロードできる」テストを追加（実機不要・1秒） | 発生には手動でのテンプレ削除/リネームが必要。startup warn がファイル名を名指しし、トレースバックにキー名が出るので診断は容易 |
| L-M6 | `tools/ops/result_log.py:67`, `tools/ops/run_until.sh:27`, `tests/test_detect_dialogs.py:22`, `tests/test_roi_scale.py:21` | `AutoLive.__new__(AutoLive)` で偽インスタンスを作って `detect()` を借りる箇所が4つ。その代償が `tools/autolive.py:1095` の `getattr` 防御 | M-11 の `recognize.classify()` 自由関数化で `__new__` ハック3箇所と getattr 防御が同時に消える | 既に private 属性 `_last_dark_check` が ops ツール2本にコピーされている。壊れ方は間欠的（暗いフレームでのみ AttributeError）で動作確認をすり抜けやすい |
| L-M7 | `tests/test_repo_layout.py:42-49`, `tests/test_corpus_smoke.py`, `tests/test_roi_scale.py` | ops/probes のファイル名リスト完全一致（正当な追加でテストが赤くなり、バグは1つも見つからない）、`py_compile` のみ、戻り値を見ないスモーク | 完全一致リストを不変条件テストに置き換える（「tools 直下の .py は3本だけ」は残す価値がある）。`ROI_SCALE_BY_DISTANCE=True` の4件は既定OFFなので1件に減らすか skip 理由を明示。グローバル書き換えは `unittest.mock.patch.object` へ | 「(a)(b)(c)で11件」は約2倍の水増し（実数5件/52件）。「detect()・打鍵・座標変換がほぼ無防備」も誤り（`test_detect_dialogs` / `test_dark_detect_perf` / `test_autocal` がカバー）。本当に無防備なのは **LIFE 安全のみ**（= M-13） |
| L-M8 | `.gitignore:18`, `tests/test_dark_detect_perf.py:30-31` | `/tests/corpus_raw/` が gitignore され、クリーンクローンでは5件が skip される。うち `TestPauseSearchBox` の2件は**コーパス不要**（定数チェックのみ）なのにクラス単位 skipUnless に巻き込まれている | コーパス不要な2件を skipUnless の無い別クラスへ移す。pause 3枚 / gameplay 3枚を `tests/frames/` に git 管理でコミットして必須テスト化 | 「無言 skip」は誤り（`OK (skipped=5)` と件数が出る）。CI は存在しない（`.github` 自体が無い）。`docs/README.md` に「コーパスが無ければ skip される」旨は既に記載済み |
| L-M9 | `tools/probes/*.py` | 9本が module トップレベルで `AutoLive(...)` を構築、`autolive.CIRCLES` / `P_RESUME` / `ARC_CENTER` を参照 | 結論が確定した7本は git tag を打って削除、まだ使う4本（`trigger_test` / `pause_ab` / `color_probe` / `result_grab`）は `driver` と小さな `probe_support.py` だけに依存するよう書き換える | 「リファクタのたびにテストが赤くなる」は**実測で否定**（`P_RESUME` をリネームしても52件すべて緑のまま。`test_repo_layout` は import ではなく `py_compile` するだけ）。残るのは「再実行時にしか露見しない stale コード」のみ |
| L-M10 | `tools/autolive.py:500-590` | `_click_screen` が毎回 `os.environ.get("I7_CLICK_MODE")` を読み、8方式の実験ディスパッチへ分岐する | 現状維持を推奨（整理するなら `tools/probes/pause_ab.sh` の同時改修が必要） | 環境変数を設定しているのは `tools/probes/pause_ab.sh:17` のコマンド前置のみでスコープが漏れない。誤設定時の else 節は baseline と**完全に同一のイベント列**。実測コスト 290ns/回。`docs/device-findings.md:62-65` に意図的に残している旨が明記済み |
| L-M11 | `tools/autolive.py:64-279` | 定数ブロックに普遍値・機種依存・チューニング値・安全装置が混在 | M-10 の削除とセットで `# [device]` `# [tuning]` `# [invariant]` のタグを付ける | 「安全装置を打鍵チューニングのつもりで緩める」経路は存在しない（`STUCK_STOP_SEC` 等に CLI 引数が無い）。「NOTE_ROI_LEAD を機種問題だと思って触った事故」も因果が誤り（3.3FPS 事故の原因は PAUSE 照合のコスト） |

### ドキュメント

| ID | 対象 | 概要 | 対処 |
|---|---|---|---|
| L-D1 | `docs/screen-transitions.md:47-75` | 判定順テーブルに `battery` / `resumelive` / `liveassist` の3状態が欠落（docs 全体で resumelive/liveassist はどこにも記載が無い）。§6.2 の「システムダイアログは自動タップしない方針」も、実装が battery 警告の「閉じる」を自動タップしている点と食い違う | 3行を追加し、コード側コメントの根拠（battery=最優先で閉じないと未知画面停止 / resumelive=cardx より先でないと停滞 / liveassist=formation より先）も備考に転記。§6.2 に battery 例外を追記 |
| L-D2 | `docs/navigation.md:59, 84-94` | 「オート OFF トグル（要 ON 化）」「ブースト=3倍 / **オート=ON** / ループ=5回」が訂正注記なしで残存。同じファイルの (B) 節（L150-160）にだけ訂正が入っている | L59 を「オートは常に OFF」に書き換え、L84-94 の引用ブロックに (B) 節と同じ訂正注記を付けるか `archive/original-design.md` へ退避 |
| L-D3 | `docs/README.md:49-113` | 索引（L1-38）の後ろに旧 specification の §1/§3/§13/§17.3/改訂履歴が本文のまま残り、「AUTO 周回」「OCR 取得・記録」を前提にしている。改訂履歴も 0.15（2026-07-30）で止まっている | §1/§3/§17.3 を archive へ移すか冒頭に「※当初設計。AUTO 周回・OCR は不採用/未実装」を明記。改訂履歴に 2026-07-31 の 3.3FPS 修正・円補正・オート不使用決定、2026-08-01 の ops スクリプト追加を追記 |
| L-D4 | `docs/architecture.md:47-53, 93-122, 126-177` | §7.1 のディレクトリ構成図が `assets/templates/{live,stamina,popups}/` を示す（実際はフラット28ファイル）。§7.2/§17.1 のテンプレチェックリストが現行 `TEMPLATES` 17キーと1つも重ならない。§7.4 の `expected_resolution`・§15 の `tests/fixtures/` は存在しない。§4.4 の座標変換式 `screen_pt = (Ox + mx/s, ...)` は実装と逆（mss がポイント解像度で返すのでスケール除算不要）。§5.1 は AUTO 前提。`docs/operations.md` は存在しない `doctor` コマンドを2箇所で案内 | 該当章を archive へ移すか冒頭に注記。§4.4 は実装に合わせて書き直す（`tools/driver.py:107-108` の docstring が真実）。`doctor` は `python tools/driver.py info` に置換 |
| L-D5 | `CLAUDE.md:64-65`, `docs/operations.md:7`, `assets/prompts/supervisor_loop.md:35` | `tools/ops/run_until.sh` が入口3ドキュメントに未反映（`grep -rn 'run_until' docs/ CLAUDE.md` は0件）。`tools/ops/README.md` 内でも表（「長時間の無人運用はこれを使う」）と末尾のコマンド例（supervisor 直起動）が矛盾 | **H-3 の修正を先に行うこと。** 現状の `run_until.sh` は `connected()` が `state=="menu"` を切断と誤診する未検証コードなので、入口3ドキュメントを一斉に書き換えるのは時期尚早。H-3 で切断判定を supervisor に移すなら run_until 自体が不要になる |
| L-D6 | `docs/screen-transitions.md:195` | 「ESC キー \| `esc_pressed()` を2回連続検出」が古い（実装は `ESC_HOLD_SEC = 1.2` 秒の長押し） | 「ESC を1.2秒押し続ける（グローバル検出）。`--no-esc` 指定時は無効」に修正。正しい情報は `tools/autolive.py:38-41` の docstring と `--help`、`docs/operations.md:59` に既にある |
| L-D7 | `assets/prompts/supervisor_loop.md:8, 27, 37, 51` | `§17.6`〜`§17.10` を参照しているが、`docs/specification.md` は17行の案内スタブ。`§17.8`〜`§17.11` は移動先で日付付き見出しに付け替えられ、番号での grep が対応表経由の2ホップになる | `§17.x` 参照を現行ファイル名＋見出しに置換（例: 『§17.10』→『docs/device-findings.md「再接続後の PAUSE 再燃（2026-06-08）」』）。`§17.6 E` と `§17.7` は見出しに番号が残っているので grep 一発で解決する |
| L-D8 | `CLAUDE.md:99-120`, `assets/prompts/README.md` | copilot モジュール（`screen_triage` / `result_ocr` / `nav_verify`）を呼ぶコードが存在しないのに、未実装である旨の注記が `7414dfa` の縮約で削除された。`assets/prompts/README.md` の対応表にも実装状況の欄が無い | CLAUDE.md に1行「`screen_triage` / `result_ocr` / `nav_verify` を呼ぶコードは未実装（プロンプトとスキーマのみ）」を復活。README 対応表に「実装状況」列を追加（Phase 3 のみ即使用可） |
| L-D9 | `docs/setup.md:14-17, 41-55` | 依存に `ocrmac` / `PyYAML` / `pydantic` / `typer` / `pynput` が並ぶが、5つとも一切 import されていない。`pyobjc-framework-AppKit` は **PyPI に存在しない配布名**（AppKit を提供するのは `pyobjc-framework-Cocoa`）。pip install 行が1つも無い。§2.5 の「起動時にサイズ不一致を警告」は未実装。「マルチスケール対応は将来拡張」も古い（`SCALES` で実装済み） | 実際の6パッケージに揃え、`CLAUDE.md` と同じ pip install 行を転記して setup.md 単体で完結させる。§14.1 の表は「当初設計・未使用」と明記するか archive へ。キルスイッチの `pynput` は `Quartz.CGEventSourceKeyState` に修正 |
| L-D10 | `docs/note-engine-dev.md:10-11` | 「現行 `CIRCLES` は5要素で中央(index2)はダミー」が実装(4要素)と食い違う。rotate の「5円」表記も `tools/autolive.py:14, 161, 1222` と `docs/architecture.md:248` の4箇所に残る | 「現行 CIRCLES は4要素（中央ダミーは削除済み）」に修正。「5円」表記5箇所を「4円」に |
| L-D11 | `tools/README.md:6` | 「`tools/ops/` \| 無人運用ウォッチャ**8本**」が実態10本（`run_until.sh` と `result_log.py` が後から追加された）。probes 12本・本番3本は一致 | 「10本」に修正するか件数表記をやめる。`tests/test_repo_layout.py` に README の件数と実ファイル数の一致を検査するアサーションを足せば自動追従する |
| L-D12 | `docs/device-findings.md:277-283` | 「スコア向上レバー: `--flick` 済み → `--predict` の緑ホールド満点化が次の候補」が `docs/operations.md:27` の残課題（「GOOD 158 に対し PERFECT 17。lead を詰める余地」）と食い違う | 優先順位を (1) GOOD→PERFECT 転換、(2) BAD/MISS 削減（L-A2 / M-6）、(3) 種別対応 の順に書き直す。種別対応の前に「DAZ EASY に緑/青が実際に何本あるか」を数えること（現状これを誰も数えていない） |
| L-D13 | — | 人手プレイのベースラインが同一曲・同一条件で記録されていない（自動 = Don't Analyze Me 184ノーツ / 人手 = Ache 103ノーツ で比較している） | 同一曲（Don't Analyze Me / EASY / ブースト3倍 / 同一編成）で人手1ライブを1回記録し、唯一のベースラインにする。自動同士の A/B 基準は `docs/operations.md:17` に既にあり、欠けているのは理論上限の参照点だけ |
| L-D14 | `tools/autolive.py:86-118, 248-250` | セクション見出しが「すべて内容矩形相対」と宣言しているが、直下の定数は「窓相対・実測」（M-10 と同一）| M-10 に統合 |

---

## 実機を動かす際の確認項目

実機（iPhone ミラーリング）でしか確認できない項目のチェックリスト。**ログ文字列と数値で
判定できる形**にしてある。周回を止めると LIFE を消費するので、上から順に確認して
「異常があれば次に進まない」運用にすること。

判定に使うログは `/tmp/i7_autorun.log`（autolive）、`/tmp/i7_supervisor.log`（supervisor）、
`/tmp/i7_runner.log`（run_until.sh）。

### A. 起動前（周回を始める前に必ず）

| # | 確認 | 方法 | 正常 | 異常なら |
|---|---|---|---|---|
| A-1 | **多重起動していない** | `ps -eo pid,command \| grep -vE "zsh -c\|grep" \| grep -E "run_until\|supervise_autolive\|tools/autolive"` | 0件 | 既存を停止してから開始（[M-5](#m-5-ops-スクリプトに排他制御が無い)） |
| A-2 | ミラーリングが接続されている | `.venv/bin/python tools/driver.py info` | `w > h`（横向き。例 671x348） | 縦長なら切断中。iPhone をロックして再接続 |
| A-3 | ミラーリングが最前面 | `osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true'` | `iPhone Mirroring` | 他アプリの背後だと暗い画面を gameplay と誤認する |
| A-4 | **オートライブ OFF** | 楽曲選択下部パネルを目視 | `ブースト 3倍 / オート OFF` | ON だと1ライブにつきブリンドリンク3個を消費（**大前提**） |
| A-5 | 難易度 EASY・対象曲 | 楽曲選択画面を目視 | `EASY+` ＋ 対象曲がハイライト | 違えばイベント効率が落ちる |
| A-6 | **きなこパン残量** | LIFE 不足ダイアログを開いて目視、または前回ログの `きなこパンで回復` 回数から逆算 | 想定周回数ぶん残っている | **0 だとステラを消費する**（[C-1](#c-1-きなこパン枯渇時に-anch_kinako-がステラの回復ボタンを直撃する)。修正前は特に必須） |
| A-7 | **ステラ所持数を記録** | LIFE 不足ダイアログの「所持 N」を控える | — | 周回後に**減っていないこと**を確認するため。C-1 の再発検知はこれしかない |
| A-8 | 終了時刻が休憩時間に食い込まない | `date -r <target_epoch>` | 00:00〜07:59 を含まない | 休憩時間は周回しない方針 |

### B. 起動直後（最初の1ライブ）

ここで異常があれば**ライブに入る前に止める**（LIFE を使わずに済む）。

| # | 確認するログ | 正常 | 異常の意味 |
|---|---|---|---|
| B-1 | `[auto-circles] 前回の補正値を復元（<W>x<H>）` または `[auto-circles] 円座標を実測へ補正` | どちらかが出る | 出ないと円がズレたまま打鍵する（実測 MISS 51・グレード B） |
| B-2 | `[auto-circles] 検出N円 (累計M) → まだ確定せず` | 数回で収まる | 延々出続けるならリング検出が失敗している。ライブ画面が想定と違う可能性 |
| B-3 | `楽曲選択 → <曲名> を選択 (score=…)` | score ≥ 0.72 | `対象曲が見つからず曲は変更しない` が続くならテンプレを撮り直す |
| B-4 | `フレンド選択 → 最上段を選択` | 出る | 出ないなら `friendselect` テンプレが当たっていない |
| B-5 | `編成画面 → START` | B-4 の直後に出る | 間に `カードポップアップ → 背景タップで閉じる` が挟まるなら `CARDX_SUPPRESS_SEC` が効いていない |

### C. ライブ中（1曲終わるごと）

| # | 指標 | 取り方 | 正常 | 異常の意味 |
|---|---|---|---|---|
| C-1 | **ループ周波数** | `★ライブ クリア（通算N） 打鍵A回 / 判定Bフレーム` の B ÷ ライブ長(約115秒) | **30 FPS 前後**（判定 3,500〜4,500） | 大きく下回るならパラメータではなく**処理の重さ**が原因。ここを直すまで lead を触らない |
| C-2 | **打鍵回数 vs ノーツ数** | A と リザルトの PERFECT+GOOD+BAD+MISS | A ≧ ノーツ数 | A < ノーツ数なら**検出**の問題（円座標・しきい値）。A ≧ なのに MISS が多いなら**タイミング**の問題 |
| C-3 | PAUSE 発生 | `grep -c "PAUSE → 再開"` | **0** | 数秒周期で出るなら合成入力が genuine と認識されていない（再接続病）。iPhone 本体の電源再投入 |
| C-4 | 実マウスを動かしていない | — | 触らない | 実行中はカーソルがクリック点へワープし続ける。触ると打鍵が乱れる |
| C-5 | ホスト側で他コマンドを叩いていない | — | 叩かない | フォーカスを奪うとミラーリングが背面に回り、暗い画面を gameplay と誤認して停止する |

### D. リザルト（成績の確認）

| # | 確認 | 正常 | 異常の意味 |
|---|---|---|---|
| D-1 | MISS | 一桁 | 二桁以上なら C-1/C-2 に戻って切り分ける |
| D-2 | BAD | 数個 | 多いなら早撃ち過多／不足 |
| D-3 | SCORE・グレード | 目標水準に達している | — |
| D-4 | 成績の**分布** | `tools/ops/result_log.py montage <tag>` で複数ライブを1枚に | 同一設定でも ±5% ばらつく。**単発比較で結論を出さない** |

### E. 長時間運用中（定期的に）

| # | 確認 | コマンド | 正常 | 異常なら |
|---|---|---|---|---|
| E-1 | `[warn]` の有無 | `grep "\[warn\]" /tmp/i7_autorun.log \| tail` | 0件 | 保存されたスクショ（`/tmp/i7dbg/*_*.png`）を見て原因を特定し、テンプレ資産化する |
| E-2 | **空転していない** | `grep -c "完了: 0 回クリア" /tmp/i7_autorun.log` | 増えない | 増え続けるなら同じ画面で再起動を繰り返している（[H-1](#h-1-安全停止が終了コードに現れず-supervisor-が無条件に再起動する)/[H-2](#h-2-per-song-result-が-cardx-と誤判定され再起動トラップになる)） |
| E-3 | クリアが進んでいる | `grep -c "★ライブ クリア" /tmp/i7_autorun.log` | 時間に比例して増える | 増えないのに supervisor が再起動していたら停止して調べる |
| E-4 | **きなこパン回復の連続回数** | `grep "きなこパンで回復" /tmp/i7_autorun.log \| tail -3` | `（1回目, ステラ不使用）` が中心 | 回数が `MAX_LIFE_RECOVERS`=6 に近づいたら枯渇が近い。**枯渇＝C-1 の発火条件** |
| E-5 | ミラーリング切断 | `tail /tmp/i7_runner.log` | `supervisor 起動` のまま | `ミラーリング切断中…待機する` なら iPhone をロックする |
| E-6 | ディスク | `du -sh /tmp/i7dbg` | 肥大しない | デバッグスクショが溜まり続けるので適宜削除 |

### F. 周回終了後（必ず）

| # | 確認 | 判定 |
|---|---|---|
| F-1 | **ステラ所持数が A-7 から減っていない** | 減っていたら **C-1 が発火した**。即座に周回を止め、きなこパンを補充するまで再開しない |
| F-2 | きなこパン残量 | 次回の周回可能時間を見積もる |
| F-3 | 総クリア数と `[warn]` 件数 | 記録して前回と比較する |
| F-4 | プロセスが残っていない | `ps` で runner / supervisor / autolive / result_log / `caffeinate -dimsu` が 0 件 |

### 停止しきい値の早見表

安全停止に至る条件。ログに出たら**何が起きたか**の手掛かりになる。

| 定数 | 値 | 発火条件 | ログ |
|---|---|---|---|
| `STUCK_STOP_SEC` | 25.0秒 | 未知画面／閉じられないポップアップに滞留 | `[warn] 未知画面に Ns 停滞` ほか |
| `RESULT_STUCK_SEC` | 30.0秒 | Result 送りが進まない | `[warn] Result送りが Ns 進まず停滞` |
| `GAMEPLAY_TIMEOUT_SEC` | 240.0秒 | 暗い画面が続く（切断オーバーレイの誤認など） | `[warn] gameplay が Ns 継続` |
| `MAX_LIFE_RECOVERS` | 6 | LIFE 不足が連続（きなこパン枯渇の可能性） | `[warn] LIFE不足が継続` |
| `MIN_LIVE_SEC` | 20.0秒 | これ未満の gameplay はクリアに計上しない | — |

### 打鍵パラメータを変えるときの手順

1. **C-1（ループ周波数）と C-2（打鍵回数）を先に確認する。** 30 FPS を大きく下回るなら
   パラメータではなくそこを直す
2. 変更は**1つずつ**。2つ同時に変えると効果を切り分けられない
3. `tools/ops/result_log.py` で**複数ライブ**回してから比較する（単発は誤差に埋もれる）
4. ライブの途中で止めない。リザルト画面になってから入れ替える
   （`detect()` が `gameplay`/`pause` を返す間は待つ）

---

## 着手順の提案

このプロジェクトは実機（iPhone ミラーリング）が無いと検証できない変更が多く、周回を止めると LIFE を消費する。**実機不要なものから順に片付ける**のが原則。

### フェーズ 0 — 実機不要・即座に着手（コードとテストのみ）

依存関係が無く、単体で完結する。この順で進めれば各段階でテストが緑のまま保てる。

| 順 | 項目 | 内容 | 検証手段 |
|---|---|---|---|
| 0-1 | **H-1** | `EXIT_SAFE_STOP=42` の導入と supervisor 側の `rc==42` 分岐、サーキットブレーカ、バックオフ | シェルのモック実行。実機不要 |
| 0-2 | **M-3** | `freeze_sentinel.sh` の `grep -c \|\| echo 0` を3箇所修正 | zsh で `0\n0` が出ないことを確認。実機不要 |
| 0-3 | **M-1** | `detect_content_rect` の採用条件に暗さゲートを追加 | `tests/corpus_raw` の formation/songselect フレームで content が (38,325) のまま or 未採用になることを確認 |
| 0-4 | **M-12** | ground truth を目視確認したフレームを `tests/frames/<state>/` にコミットし、`detect()` の回帰テストを整備（fresh インスタンス／`_last_dark_check=0.0` を忘れずに） | これ自体がテスト |
| 0-5 | **M-13 + C-1(3)** | LIFE 回復の回帰テスト（きなこパン枯渇フレームでの着弾点検証）を追加 | これ自体がテスト。**C-1 の実装より先に入れる**（レッドから始める） |
| 0-6 | **M-7(1)** | `note_engine.detect_notes` の bbox 化（出力完全一致を確認済み。帯クロップは後回し） | `tests/test_corpus_smoke.py` を強化して before/after の blob 集合一致を検証 |
| 0-7 | **M-10 + L-D14** | 未参照の座標定数20個＋`TRACK_FORGET_SEC` を削除。`P_RESUME` は probes 側でインライン化してから削除。セクション見出しを修正 | `unittest discover -s tests`。probes は `py_compile` で通ってしまうので目視で参照を潰す |
| 0-8 | **L-M3, L-M4, L-M5** | `_note_present` 削除、`formation` 二重判定と `"download"` 削除、テンプレ全キー存在テスト追加 | テスト |
| 0-9 | **ドキュメント一括**（L-D1〜L-D14、M-15、M-16、M-14） | 実装と食い違う記述の修正。特に **M-16（曲は変更しない）と M-14（オートOFF）は誤操作に直結する**ので優先 | `tests/test_docs_links.py` が通ること |

### フェーズ 1 — 実機フレームの取得だけ必要（周回停止は数分）

`tools/driver.py shot` / `clickshot` でフレームを撮るだけ。周回を長時間止める必要はない。

| 順 | 項目 | 必要な実機作業 |
|---|---|---|
| 1-1 | **C-1** | きなこパン**あり**の LIFE 不足ダイアログを撮影し、`assets/templates/kinako_row.png` を切り出す。枯渇時フレームは既に `tests/corpus_raw/lifeshort/` にある |
| 1-2 | **H-2** | `/tmp/i7dbg/cardx_stuck_27.png` を `tests/frames/` へ（撮影済み）。`prev_result_dialog` の専用テンプレを追加するなら1枚撮影 |
| 1-3 | **M-12(4)** | コーパスに無い `story` / `resumelive` / `eventresult` / `liveassist` / `rankup` のフレームを取得 |
| 1-4 | **M-13(4)** | イベント装飾版の lifeshort フレームを取得 |

### フェーズ 2 — 実機周回での検証が必要（LIFE を消費する）

**フェーズ 0/1 を先に完了させ、1回の周回セッションでまとめて検証する。**

| 順 | 項目 | 検証内容 | 備考 |
|---|---|---|---|
| 2-1 | **C-1 の実装** | きなこパン行の照合→クリック、枯渇時に停止すること | 最優先。1回の LIFE 不足で検証できる |
| 2-2 | **H-2 の修正** | 連続ラン判定に変えても通常の cardx（報酬/アイテム獲得）が閉じられること | Result 通過を数周見る |
| 2-3 | **H-3 / H-4 / M-5** | supervisor の切断待機・ロック・停止フラグ | iPhone を触って意図的に切断して確認 |
| 2-4 | **M-2** | ウィンドウ矩形の周期再取得。`find_window()` は重いので**打鍵ループの FPS が落ちないこと**を「打鍵N回 / 判定Mフレーム」ログで確認 | FPS が 26〜37 を維持すること |
| 2-5 | **M-6** | `--flick` 検色点を飛行線に載せ替え、`FLICK_APPROACH_FRAC` を再較正。**外側2レーン（c0/c3）の赤検出率が上がるか**を確認 | `result_log.py` で複数ライブの分布を取る（単発比較は ±5% の誤差に埋もれる） |
| 2-6 | **M-9** | `ANCH_RESUME` の y 見直し（SE で下端1pxしか余裕が無い） | PAUSE を意図的に発生させて確認 |
| 2-7 | **L-A1** | `ARC_CENTER` → `SPAWN` 基準への統一。lead 方向のずれ 18〜31° を解消 | lead の再測定とセット。**`--note-lead 0` にはしないこと** |
| 2-8 | **L-A2** | keepalive を中央ダミー (0.49,0.93) へ移設。**PAUSE が増えないことを1ライブぶん確認する** | HID アイドル判定はクリック位置に依存しないはずだが要確認 |
| 2-9 | **L-A4** | `time.sleep(0.005)` の削減。**`NOTE_ROI_LEAD` の再測定が前提** | 単独では改善が出ない可能性が高い |

### フェーズ 3 — 構造改善（M-12 のテストが揃ってから）

| 順 | 項目 | 前提 |
|---|---|---|
| 3-1 | **M-11 の分割** | M-12（`detect()` 回帰テスト）が必須。移行順は `geometry` → `recognize` → `actuator` → `tapper` → `calibration`/`watchdog` → FSM |
| 3-2 | **L-M2**（`CIRCLES` のインスタンス化） | M-11 の `tapper.py` 切り出しと同時に行う |
| 3-3 | **L-M6**（`__new__` ハックの解消） | M-11 の `recognize.classify()` が入れば自動的に消える |
| 3-4 | **M-4**（状態別 watchdog + 進捗 watchdog） | M-11 の `watchdog.py` 切り出しと同時（現在7箇所のコピペを1箇所に） |
| 3-5 | **L-M9**（probes の整理） | M-10 の `P_RESUME` 削除の前提。git tag を打ってから削除 |
| 3-6 | **M-8**（`_release_hold()`）、**L-A5**（`consume` の時刻窓） | `--predict` の実機検証を再開するときにセットで |

### 依存関係まとめ

```
C-1（ステラ誤押下）
 ├── 前提: M-13（回帰テスト）── フェーズ0で先に赤く
 └── 増幅器: H-1（rc 分離）── 同時に入れないと被害が止まらない

H-1（rc 分離）
 └── 派生: M-5（排他）/ H-4（停止フラグ）── ops の停止経路を1本化

H-3（切断ガード）
 ├── H-4 と同じ「ラッパー2階層」問題 ── まとめて設計する
 └── L-D5（docs 反映）は H-3 完了後に

M-11（分割）
 └── 前提: M-12（detect 回帰テスト）── これ無しで着手しない
      └── 前提: フェーズ1 のフレーム取得

M-6 / L-A1（飛行線の幾何）
 └── 共通関数に切り出して両方同時に直す（別々に直すと基準点が再び分裂する）
```

---

## 今回のレビューで確認できなかったこと

正直に列挙する。以下は本書の記述の確度が下がる部分である。

1. **実機での動作確認は一切していない。** 本レビューはコード・リポジトリ内の実機キャプチャ（`tests/corpus_raw/`, `assets/screens/`, `/tmp/i7dbg/`）・実運用ログ（`/tmp/i7_autorun.log`, `/tmp/i7_supervisor.log`）の静的解析と、それらに対する関数のオフライン実行のみで行った。ミラーリングを接続しての再現・修正後の検証は行っていない。

2. **C-1 の「ステラが実際に消費された」ことは間接証拠のみ。** ステラ所持数が 58→55→52 と消費数量欄の「3」ちょうどずつ減っている事実と、着弾点がボタン矩形中央に入る計算に基づく。ゲーム内の消費履歴は確認していない。**きなこパンが 0 でない状態で同じダイアログがどう見えるか**（きなこパン行が上・ステラ行が下の2段構成であること）は `docs/navigation.md` の記述に依拠しており、その実キャプチャはリポジトリに存在しない。

3. **`liveassist` / `story` / `eventresult` / `rankup` / `resumelive` の実フレームが1枚も無い。** `tests/corpus_raw/` の14ディレクトリにこれらは含まれず、`tests/frames/` にあるのは story と resumelive の2枚のみ。これらの状態に関わる指摘（`ANCH_LIVEASSIST_START` の44pxずれ等）は**すべて未検証の推測**として扱った。

4. **iPhone16 系（671x348）のコーパスがほぼ無い。** `tests/corpus_raw/` は529x334（SE）が中心で、機種差に関する検証（M-9 のスケール問題、M-6 の検色点、L-A1 の幾何）は SE のフレームからの外挿と計算に頼っている。実機は 671x348 で運用されているため、SE で成立した結論が本番機でどうなるかは別途確認が必要。

5. **`--predict` / `--engine track` / `--holds` の実挙動。** いずれも既定 OFF で、`tools/ops/` のどのスクリプトも渡していない。これらに関する指摘（M-8, L-A5, L-M1）は**コードの静的解析と部分的な単体再現**のみで、実機で有効化したときに何が起きるかは分かっていない。`docs/note-engine-dev.md` の「track は recall ≈6%」という記録も、当時 `--auto-circles` を併用すると L-M1 のクラッシュで起動できなかったはずなので、測定条件が正確には再現できない。

6. **`recover_freeze.py` の復旧シーケンス全体。** ⌘1/⌘2/上スワイプ/Spotlight による強制終了→再起動→ナビは、実行するとゲームが落ちるためオフラインで検証できない。H-4 の「復旧中の衝突」は制御フローの読解と各スクリプトの起動タイミングからの推論。

7. **`ROI_SCALE_BY_DISTANCE` を既定 OFF にした判断の妥当性。** `/tmp/i7dbg/results/roi_scaled/` に画像が1枚しか無く（n=1）、「P33→P29 で誤差に埋もれた」という結論を再評価できなかった。L-A1 で指摘したとおり、その根拠にした「移動距離の1.34倍差」自体が `ARC_CENTER` 基準ゆえの誤りなので、基準点を `SPAWN` に直したうえで測り直す価値がある（実距離は4円とも243〜246pxでほぼ等距離＝そもそもスケーリングの前提が無い可能性が高い）。

8. **判定閾値の最適値。** `result` の 0.55、`songdaz` の 0.72、`pause` の 0.78 などについて、実機コーパスでの分布は測ったが、**イベント装飾が変わったときにどう動くか**は分からない。`songdaz` は実測 0.62〜0.65 で閾値 0.72 に届いておらず「一度も曲を選べていない可能性」があるが、実運用ログには「楽曲選択 → Don't Analyze Me を選択 (score=0.79)」という行があり、コーパスのフレームと実運用のフレームで条件が違う。**実機で `songdaz` が実際に当たっているかの確認は未実施。**

9. **きなこパンの実在庫と消費実績。** 消費率 0.664個/周はログの `LIFE不足 → きなこパンで回復` の出現回数から算出したが、C-1 によりそのうち何回が実際にはステラだったかは切り分けられていない。**この数字自体が C-1 の修正後に測り直す必要がある。**