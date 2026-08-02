# docs/ の整理 設計書

- 日付: 2026-08-02
- 状態: 設計確定（実装前）
- 対象: `docs/` 配下の Markdown（`docs/superpowers/` を除く）

## 1. 背景

`docs/` は12ファイル・3,180行に膨らみ、性質の違う4種類が混在している。

1. **現役の仕様** — README / architecture / device-findings / navigation / operations / setup / screen-flow
2. **重複** — `screen-transitions.md` は 2026-08-02 に新設した `screen-flow.md` と §1・§2・§3・§6 が重なる
3. **陳腐化** — `note-engine-dev.md` は「現行 `CIRCLES` は5要素で中央(index2)はダミー」と書くが、
   実際は4要素（`len(autolive.CIRCLES)` == 4）。2026-06-06 から更新されていない
4. **役目を終えたもの** — `specification.md`（17行の転送スタブ）、
   `archive/original-design.md`（「実装されていない」と明記された当初設計）、
   `improvements.md`（レビュー結果。Critical/High は全て修正済み）

読み手が「どれが真実か」を判断するコストが上がっている。**嘘のドキュメントは無いより悪い**
（実際に、実装と食い違うドキュストリングを信じて実機で事故を起こしている）。

## 2. 方針

上記 2〜4 の**5ファイルを削除**する。削除後は7ファイル・1,486行（現在の47%）。

ユーザー確認済みの判断（2026-08-02）:

- 重複・陳腐化したものを消す
- 履歴的価値だけのものも消す（git 履歴に残るため）
- 転送スタブも消す（参照元を書き換える）
- レビュー結果も消す（未対応項目のリストは失われることを承知のうえ）

## 3. 削除するファイル

| ファイル | 行 | 削除理由 |
|---|---|---|
| `docs/screen-transitions.md` | 319 | `screen-flow.md` と重複。固有の実測座標は2件のみ |
| `docs/note-engine-dev.md` | 80 | 記述が事実と異なる。2ヶ月更新なし |
| `docs/archive/original-design.md` | 182 | 未実装の当初設計。履歴のみ |
| `docs/specification.md` | 17 | 分割後の転送スタブ |
| `docs/improvements.md` | 1,096 | Critical/High は全て修正済み |

`docs/archive/` は空になるのでディレクトリごと削除する。

## 4. 削除前に救出する内容

そのまま消すと、**ユーザーが明示的に依頼した成果物**が失われる。次の2点だけ救出する。

| 内容 | 現在地 | 移動先 | 理由 |
|---|---|---|---|
| 「実機を動かす際の確認項目」（97行） | `improvements.md` | `operations.md` | 2026-08-01 に依頼された成果物。起動前/起動直後/ライブ中/リザルト/長時間運用/終了後の6段階チェックリスト |
| 実測座標 `(0.644, 0.718)` `(0.86, 0.16)` | `screen-transitions.md` | `navigation.md` | 他に記録が無い |

**これ以外は救出しない。** 特に未対応の改善項目（Medium 16件・Low 58件）とレビューの経緯は
失われる。復元が必要なら `git show 6d6e34b:docs/improvements.md`。

## 5. 削除に伴う修正

| 対象 | 修正内容 |
|---|---|
| `tools/autolive.py` | コメント6箇所の `docs/specification.md §17.x` を実際の行き先へ書き換える（§17.5→`architecture.md`、§17.6/§17.8→`device-findings.md`） |
| `tests/test_docs_links.py` | `test_specification_md_is_a_redirect_stub` を削除（存在を要求しているため落ちる） |
| `tests/test_screen_flow_doc.py` | `screen-transitions.md` への言及があれば削除 |
| `docs/screen-flow.md` | 冒頭の「役割の違い」表から `screen-transitions.md` の行を削除 |
| `docs/README.md` | 索引から5行削除 |
| `CLAUDE.md` ほか | 削除ファイルへのリンクを張り替え |

## 6. 検証

1. `.venv/bin/python -m unittest discover -s tests` が `OK`
   - `tests/test_docs_links.py` が**リンク切れを検出する**ので、張り替え漏れがあれば落ちる
2. `git grep -n "screen-transitions\.md\|note-engine-dev\.md\|original-design\.md\|specification\.md\|improvements\.md"`
   の結果が、`docs/superpowers/`（当時の記録）を除いて 0 件
3. `docs/` が7ファイルであること
4. 救出した「実機を動かす際の確認項目」が `operations.md` にあること

## 7. リスク

| リスク | 対応 |
|---|---|
| 未対応の改善項目リストを失い、同じ調査をやり直す | 承知のうえ。git 履歴から復元可能なことを本書に明記した |
| `autolive.py` のコメント書き換えでリンク先を間違える | 書き換え後に `git grep` で旧パスの残存ゼロを確認する |
| 救出漏れ | 検証4で確認する |
