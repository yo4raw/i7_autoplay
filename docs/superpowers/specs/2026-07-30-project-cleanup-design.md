# プロジェクト整理 設計書（段階1: リポジトリ棚卸し＋ドキュメント再編）

- 日付: 2026-07-30
- 状態: 設計確定（実装前）
- 対象リポジトリ: `i7_autoplay`
- 前提: **振る舞いを一切変えない**。実機（iPhone ミラーリング）検証は不要。

## 1. 背景と目的

イベント周回セッション中にリポジトリを調査したところ、次の問題が確認された。

1. **`CLAUDE.md` が起動を指示している `tools/supervise_autolive.sh` が git 未追跡**。
   clone した環境には存在せず、記載どおりの無人運用ができない。
   同様に未追跡のファイルが tools 12本・assets 2ディレクトリ・tests 1ディレクトリある。
2. **`tools/` に本番コードと使い捨ての調査スクリプトが混在**。23ファイル 3,089 行のうち
   本番は 3 本（`autolive.py` 1,305 / `note_engine.py` 479 / `driver.py` 217）で、
   残り 20 本は無人運用ウォッチャか、過去の PAUSE 調査で使ったワンショット。
   どれが現役でどれが調査アーカイブかがファイル名から判別できない。
3. **`docs/specification.md` 1,056 行のうち、1〜16章は実装前に書かれた理想設計**で実態と乖離。
   §8 OCR・§9 `config/default.yaml`・§14.2 プロジェクト構成は未実装（`config/` は存在しない）。
   一方 §17 付録の 500 行超が事実上の真実（実機知見・座標・PAUSE 調査史）であり、
   `CLAUDE.md` もその要約になっている。読み手が「どれが真実か」を判断できない。
4. **`tests/corpus_raw/`（14状態・507枚・69MB）が未追跡**。実機なしで `detect()` の
   回帰を検証できる唯一の資産だが、現状は smoke テストがクラッシュ有無を見るだけで、
   別環境では存在すらしない。

目的は、**将来の自分（および LLM copilot）が迷わず現役の資産へ到達できる状態**にすること。

## 2. スコープと段階分け

本設計書は**段階1のみ**を扱う。段階2・3は別 spec とし、本 spec の完了後に着手する。

| 段階 | 内容 | 前提条件 |
|---|---|---|
| **1（本 spec）** | リポジトリ棚卸し＋ドキュメント再編 | なし |
| 2（別 spec） | `autolive.py` 1,305 行の分割 | corpus を使った `detect()` 回帰テストの整備 |
| 3（別 spec） | 運用スクリプト 7 本の役割重複の統合 | iPhone 復旧後の実機確認 |

段階1で `autolive.py` / `driver.py` / `note_engine.py` の中身は**1行も変更しない**。
これが「振る舞い不変」の担保であり、検証項目 5 で機械的に確認する。

### 非対象

- 本番3ファイルのリファクタリング（段階2）
- 運用ウォッチャの統廃合・機能変更（段階3）
- テンプレ画像・座標定数のチューニング
- §17.10（合成入力が genuine と認識されない）の解決そのもの

## 3. リポジトリ棚卸し

### 3.1 `tools/` の3分類

```
tools/
  autolive.py  driver.py  note_engine.py  README.md      ← 本番（3）
  ops/                                                    ← 無人運用（8）
    supervise_autolive.sh  freeze_sentinel.sh  morning_watcher.sh
    pause_guard.sh  reconnect_watcher.py  recover_freeze.py
    unlock_watcher.py  corpus_collector.py  README.md
  probes/                                                 ← 調査用ワンショット（12）
    trigger_test.py  idlekeeper.py  capture_click.py  color_probe.py
    color_probe2.py  focus_probe.py  focus_state_monitor.py
    hidmove_test.py  pause_ab.sh  pause_monitor.py
    pure_observe.py  result_grab.py  README.md
```

分類の基準:

- **本番** = 周回そのものを実行する。`autolive.py` から到達可能。
- **ops** = 周回を無人で回し続けるために外側から回すもの。人間が起動する。
- **probes** = 特定の疑問に答えるために書かれ、答えが出た後も再現手段として残すもの。
  周回には不要。`docs/device-findings.md` の記述から参照される。

### 3.2 移動で壊れる参照（実装時の必須修正）

調査済みの箇所。すべて修正してから移動を完了とする。

| 種類 | 対象 | 修正内容 |
|---|---|---|
| Python import | `ops/` の `reconnect_watcher.py` `recover_freeze.py` `unlock_watcher.py` `corpus_collector.py` | `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` が1階層ずれる。`os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")` へ |
| Python import | `probes/` の `color_probe.py` `color_probe2.py` `hidmove_test.py` `focus_state_monitor.py` `pure_observe.py` `pause_monitor.py` `trigger_test.py` `result_grab.py` `idlekeeper.py` | `sys.path.insert(0, 'tools')` は CWD 依存。`__file__` 基準へ統一し、実行場所非依存にする |
| シェル | `tools/ops/freeze_sentinel.sh` 49行・51行 | `tools/recover_freeze.py` → `tools/ops/recover_freeze.py`、`tools/supervise_autolive.sh` → `tools/ops/supervise_autolive.sh` |
| ドキュメント | `CLAUDE.md:143` | `nohup tools/supervise_autolive.sh` → `tools/ops/...` |
| ドキュメント | `assets/prompts/supervisor_loop.md:35` | 同上 |
| ドキュメント | `docs/specification.md` 890 / 917 / 929-931 / 989 / 1053 行 | 再編後の新ファイルへ移設する際に新パスで記述 |
| Docstring | 各スクリプト冒頭の「使い方:」行 | 新パスへ |

`assets/prompts/` 配下は「実装・運用時に書き直さずそのまま使う」方針だが、
**パス修正はプロンプト内容の書き換えではなく参照先の追従**なので例外として行う。

### 3.3 未追跡ファイルの取り込み

すべて git 管理下に入れる。削除するものはない。

| パス | 枚数/本数 | サイズ | 扱い |
|---|---|---|---|
| `tools/` 12本 | 12 | 26KB | 3.1 の分類でコミット |
| `assets/screens/mac_inuse/` | - | - | コミット（`unlock_watcher.py` が扱う画面の資料） |
| `assets/screens/mac_unlock_prompt/` | - | - | コミット（同上） |
| `tests/corpus_raw/` | 507 | 69MB | **全部コミット**（欠落なく回帰テストを回せることを優先） |

`.gitignore` は現状のままで十分（`__pycache__/` `*.py[cod]` `.venv/` `.DS_Store` `/tmp/i7dbg/`）。
`tests/__pycache__/` も既存ルールで除外される。

### 3.4 README

3 ディレクトリそれぞれに `README.md` を置く。各ファイル 1 行で
「何をするか」「現役か / 調査アーカイブか」「関連する docs の節」を書く。
`tools/probes/README.md` には**答えが出た疑問と結論**も併記し、
同じ調査を繰り返さないようにする。

## 4. ドキュメント再編

### 4.1 新構成

```
docs/
  README.md                     索引。「どれが真実か」を最初に明示
  setup.md                      権限付与・依存ライブラリ・接続手順
  architecture.md               2層構成・FSM・座標系・テンプレ管理
  device-findings.md            実機知見（PAUSE 調査史・ノーツ仕様・端末非依存）
  navigation.md                 イベント導線・実測座標
  operations.md                 無人運用・停止条件・復旧手順・トラブルシューティング
  screen-transitions.md         （現状維持）
  note-engine-dev.md            （現状維持）
  archive/original-design.md    未実装の当初設計（履歴として保存）
  superpowers/                  （現状維持）
```

### 4.2 移設マップ

`specification.md` の全 17 章に行き先を与える。取りこぼしを作らない。

| 移設元（`specification.md`） | 移設先 |
|---|---|
| 冒頭の⚠️注意、§1 概要、§1.3 用語定義、§3 スコープ、§13 セキュリティ・規約、§17.3 用語集、改訂履歴 | `docs/README.md` |
| §2 前提条件・動作環境（2.1-2.5）、§14.1 推奨ライブラリ | `setup.md` |
| §4 システム構成、§5.1/5.3/5.4/5.5 機能要件、§6 FSM、§7 テンプレート管理、§15 テスト方針、§17.1 テンプレチェックリスト、§17.5 実装状況 | `architecture.md` |
| §17.6 (F)、§17.8、§17.9、§17.10、§17.11 | `device-findings.md` |
| §17.4 実機ナビゲーション情報、§17.6 (A)-(E) の座標・LIFE 回復手順、§5.2 スタミナ回復 | `navigation.md` |
| §17.7 無人運用知見、§17.2 トラブルシューティング、§16 既知のリスク、§17 末尾の「起動方法（PoC）」 | `operations.md` |
| §8 OCR、§9 設定ファイル、§10 ログ、§11 エラーハンドリング、§12 CLI、§14.2-14.4 | `archive/original-design.md` |

`docs/README.md` が索引としてその役割を継ぐ。
`docs/specification.md` 自体は**削除せず 20 行程度の案内スタブに置き換える**。
`tools/autolive.py` が 6 箇所のコメントでこのパスを参照しており、段階1では本番3ファイルを
1行も変更しないと決めているため（コメントの更新は段階2で行う）。
移設時に**内容は書き換えない**（誤りの混入を防ぐため）。ただし次の3点のみ手を入れる:

1. 解決済みの仮説に付いている「未解決」表現を、結論への参照に置き換える
   （例: §17.6 E は §17.6 F で解決済みである旨が既に注記されているので、それを維持）
2. 移設に伴う節番号の参照（「§17.6 参照」など）を新ファイル名へ
3. 5.3 で述べる今回の新知見を追記

### 4.3 `CLAUDE.md` の縮約

`CLAUDE.md` は**入口と絶対規則だけ**に絞る。

残すもの:
- 概要 1 段落と「真実の情報源は `docs/README.md`」の明示
- コマンド早見（セットアップ・autolive・driver）
- **絶対規則**: LIFE 回復はきなこパンのみ・ステラ厳禁 / 難易度は EASY /
  イベントは左下リボン経由（LIVE ボタンからは pt が付かない）/ ブースト 3 倍 /
  `kCGHIDEventTap` と HIDSystemState ソース＋カーソルワープ / キャプチャは `mss` /
  未知画面では停止
- LLM copilot の起動方法

docs へ移すもの: アーキテクチャ詳細、端末非依存の実装方針、テンプレ取得手順、
非自明な制約の背景説明。

### 4.4 今回のセッションで判明した事項の記録

**`docs/device-findings.md` に追記** — §17.10 の再現記録（2026-07-30）:

- 症状は §17.10 と同一。ライブ中に約 5 秒周期で PAUSE →（自動再開）→ カウントダウン →
  再び PAUSE を繰り返し、1 ノーツも進まず SCORE は 000000000 のまま。
- **`_keep_front` は無関係**（§17.8 とは別物）。`NSWorkspace.frontmostApplication` は
  一貫して `iPhone Mirroring` を返し、activate は発生していない。
- 実カーソルのワープは機能している（`CGEventGetLocation` を 0.4 秒間隔でサンプルし、
  円座標間を移動していることを確認）。
- **`iohid_click`（IOHIDPostEvent による実 HID クリック、0.4 秒間隔）でも防げない**:
  `trigger_test.py iohid_click 40 0.4 --resume` で **40 秒間に PAUSE 8 回**
  （0.4 / 6.0 / 11.5 / 17.1 / 22.6 / 28.1 / 33.7 / 39.2 秒）。
  §17.10 の changelog に列挙されていた tap / touchclick / realclick / iohid_move に加え、
  **iohid_click も無効**であることが今回確定した。
- 完全無入力にすると約 1 秒で PAUSE し、そのまま復帰しない（idle 起因であることの裏付け）。
- 結論は §17.10 のまま: **復旧手段は iPhone 本体の電源再投入**。Mac 側の打ち手は出尽くしている。

**`docs/navigation.md` に追記** — イベント「BUDDY Night NARRATIVE」（2026/07/30 17:00 - 2026/08/06 16:59）の導線:

| 手順 | 画面 | タップ座標（ウィンドウ相対） |
|---|---|---|
| 1 | イベントトップ | イベント楽曲 `(0.7015, 0.840)` |
| 2 | イベント楽曲選択 | EASY タブ `(0.663, 0.712)` |
| 3 | 同上 | NEXT `(0.749, 0.830)` |
| 4 | フレンド選択 | 先頭行 `(0.45, 0.44)` |
| 5 | 編成確認 | START `(0.700, 0.851)` |

- 観測時のミラーリングウィンドウ: **671 × 348**（横向き、scale 2.0）。
  既存の `assets/screens/*/_full.png` は 529 × 334 で撮られており、機種/ウィンドウサイズが異なる。
- **難易度タブに表示される LIFE 15 / 30 / 45 / 60 は、ブースト 3 倍込みの実消費値**
  （素の消費は 5 / 10 / 15 / 20）。フレンド選択画面のヘッダは `♥ -15` と表示され、
  ここでも 3 倍適用後の値が出る。ブースト設定が反映されていないと誤読しないこと。
  §17.6 の「LIFE 消費 = 16（ブースト3倍時）」と同じ性質の値である。
- 楽曲選択・編成画面の下部パネルは `ブースト 3倍 / オート OFF` と表示され、これが設定済みの目印。
- フレンド選択は 1 回目のタップが画面遷移アニメーション中で無視されることがある。
  行が 3 件描画されきってから再度タップすると通る。

`docs/operations.md` には、`tools/ops/` へ移動後の起動コマンドを新パスで記載する。

## 5. 検証方法（実機不要）

実装完了の判定は次の 5 項目すべてを満たすこととする。

1. `.venv/bin/python -m unittest discover -s tests` が通る（既存 4 テスト）。
2. 移動した 20 本すべてが起動する。Python は `python -c "import ast,sys; ast.parse(open(f).read())"`
   ではなく**実際に import / `--help` 実行**して sys.path 修正が効いていることを確認し、
   シェルは `bash -n` で構文確認する。実機接続が要るものは
   「ウィンドウが見つからない」で落ちるところまでを成功とする。
3. `grep -rn "tools/\(supervise_autolive\|freeze_sentinel\|morning_watcher\|pause_guard\|reconnect_watcher\|recover_freeze\|unlock_watcher\|corpus_collector\|trigger_test\|idlekeeper\|capture_click\|color_probe\|color_probe2\|focus_probe\|focus_state_monitor\|hidmove_test\|pause_ab\|pause_monitor\|pure_observe\|result_grab\)"`
   の結果が 0 件（旧パスの残存なし）。
4. `git status --porcelain` が空（未追跡ゼロ）。
5. `git diff main -- tools/autolive.py tools/driver.py tools/note_engine.py` が空。

## 6. リスクと対応

| リスク | 対応 |
|---|---|
| ドキュメント移設中に内容を書き換えてしまい、実機で確定した事実を壊す | 移設は原則コピー。書き換えは 4.2 の3点に限定し、diff をレビューする |
| 69MB のコミットでリポジトリが重くなる | 承知の上で全部コミット（欠落なく回帰テストを回せることを優先）。今後の追加分は都度判断する |
| `tools/` 移動で無人運用が起動しなくなる | 検証項目 2・3 で機械的に確認する。段階3で統合するまで役割は変えない |
| 段階1 の最中に iPhone が復旧し、周回を再開したくなる | 段階1 は本番3ファイルを触らないため、`git stash` なしでいつでも `tools/autolive.py` を起動できる |

## 7. 完了後の次アクション

1. 段階2 の spec: `autolive.py` 分割。前提として corpus_raw を使った `detect()` の
   回帰テスト（14 状態それぞれで期待する state が返ることの検証）を先に整備する。
2. 段階3 の spec: 運用ウォッチャ 7 本の役割重複を整理し、無人運用の起動手順を 1 本化する。
3. iPhone 復旧後、`docs/navigation.md` の座標でイベント周回を再開し、
   §17.10 の復旧手順（本体電源再投入）が有効だったかを `device-findings.md` に記録する。
